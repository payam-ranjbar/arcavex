//! A JSON-RPC 2.0 client over the framed stdio transport.
//!
//! Writes are serialized through one channel so two callers can never interleave a frame, and
//! responses are routed by request id, so a slow call never steals a fast call's answer.

use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use serde_json::{json, Value};
use tokio::io::{AsyncRead, AsyncReadExt, AsyncWrite, AsyncWriteExt};
use tokio::sync::{broadcast, mpsc, oneshot};

use super::framing::{encode, FrameDecoder};

const JSON_RPC_VERSION: &str = "2.0";
const NOTIFICATION_CAPACITY: usize = 256;
const READ_CHUNK: usize = 8 * 1024;

#[derive(Debug, thiserror::Error)]
pub enum EngineError {
    #[error("engine call `{method}` timed out after {millis} ms")]
    Timeout { method: String, millis: u64 },
    #[error("engine transport closed before `{0}` was answered")]
    Closed(String),
    #[error("engine rejected `{method}`: {message} (code {code})")]
    Rpc {
        method: String,
        code: i64,
        message: String,
    },
    #[error("engine returned a response to `{0}` with neither a result nor an error")]
    Malformed(String),
}

/// One server-initiated message; MCP uses these for progress and lifecycle signals.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Notification {
    pub method: String,
    pub params: Value,
}

#[derive(Debug)]
struct RpcFailure {
    code: i64,
    message: String,
}

type Pending = Arc<Mutex<HashMap<u64, oneshot::Sender<Result<Value, RpcFailure>>>>>;

/// A connected MCP peer. Dropping it closes the write side and ends both pump tasks.
#[derive(Debug)]
pub struct McpClient {
    outgoing: mpsc::UnboundedSender<Vec<u8>>,
    pending: Pending,
    notifications: broadcast::Sender<Notification>,
    frame_errors: Arc<Mutex<Vec<String>>>,
    /// Set before pending calls are drained, so a call registered either side of the close
    /// learns about it rather than waiting for its timeout.
    closed: Arc<AtomicBool>,
    next_id: AtomicU64,
    timeout: Duration,
}

impl McpClient {
    /// Attach to a sidecar's stdout and stdin and start pumping both directions.
    pub fn connect<R, W>(reader: R, writer: W, timeout: Duration) -> Self
    where
        R: AsyncRead + Unpin + Send + 'static,
        W: AsyncWrite + Unpin + Send + 'static,
    {
        let (outgoing, outbox) = mpsc::unbounded_channel::<Vec<u8>>();
        let (notifications, _) = broadcast::channel(NOTIFICATION_CAPACITY);
        let pending: Pending = Arc::new(Mutex::new(HashMap::new()));
        let frame_errors = Arc::new(Mutex::new(Vec::new()));
        let closed = Arc::new(AtomicBool::new(false));

        tokio::spawn(write_pump(writer, outbox));
        tokio::spawn(read_pump(
            reader,
            Arc::clone(&pending),
            notifications.clone(),
            Arc::clone(&frame_errors),
            Arc::clone(&closed),
        ));

        Self {
            outgoing,
            pending,
            notifications,
            frame_errors,
            closed,
            next_id: AtomicU64::new(1),
            timeout,
        }
    }

    /// Receive every notification published from now on.
    pub fn notifications(&self) -> broadcast::Receiver<Notification> {
        self.notifications.subscribe()
    }

    /// Frames the sidecar wrote that could not be decoded, kept for the diagnostics panel.
    pub fn frame_errors(&self) -> Vec<String> {
        self.frame_errors.lock().expect("frame errors").clone()
    }

    /// Send a request and await its correlated response.
    pub async fn call(&self, method: &str, params: Value) -> Result<Value, EngineError> {
        let id = self.next_id.fetch_add(1, Ordering::Relaxed);
        let (sender, receiver) = oneshot::channel();
        self.pending.lock().expect("pending").insert(id, sender);

        let frame = encode(&json!({
            "jsonrpc": JSON_RPC_VERSION,
            "id": id,
            "method": method,
            "params": params,
        }));
        if self.outgoing.send(frame).is_err() || self.closed.load(Ordering::SeqCst) {
            self.pending.lock().expect("pending").remove(&id);
            return Err(EngineError::Closed(method.to_owned()));
        }

        match tokio::time::timeout(self.timeout, receiver).await {
            Ok(Ok(Ok(result))) => Ok(result),
            Ok(Ok(Err(failure))) => Err(EngineError::Rpc {
                method: method.to_owned(),
                code: failure.code,
                message: failure.message,
            }),
            Ok(Err(_)) => Err(EngineError::Closed(method.to_owned())),
            Err(_) => {
                self.pending.lock().expect("pending").remove(&id);
                Err(EngineError::Timeout {
                    method: method.to_owned(),
                    millis: u64::try_from(self.timeout.as_millis()).unwrap_or(u64::MAX),
                })
            }
        }
    }

    /// Send a notification, which by definition has no response to correlate.
    pub fn notify(&self, method: &str, params: Value) -> Result<(), EngineError> {
        let frame = encode(&json!({
            "jsonrpc": JSON_RPC_VERSION,
            "method": method,
            "params": params,
        }));
        self.outgoing
            .send(frame)
            .map_err(|_| EngineError::Closed(method.to_owned()))
    }
}

async fn write_pump<W>(mut writer: W, mut outbox: mpsc::UnboundedReceiver<Vec<u8>>)
where
    W: AsyncWrite + Unpin + Send + 'static,
{
    while let Some(frame) = outbox.recv().await {
        if writer.write_all(&frame).await.is_err() || writer.flush().await.is_err() {
            break;
        }
    }
}

async fn read_pump<R>(
    mut reader: R,
    pending: Pending,
    notifications: broadcast::Sender<Notification>,
    frame_errors: Arc<Mutex<Vec<String>>>,
    closed: Arc<AtomicBool>,
) where
    R: AsyncRead + Unpin + Send + 'static,
{
    let mut decoder = FrameDecoder::new();
    let mut chunk = vec![0_u8; READ_CHUNK];

    loop {
        let read = match reader.read(&mut chunk).await {
            Ok(0) | Err(_) => break,
            Ok(read) => read,
        };
        decoder.push(&chunk[..read]);

        while let Some(frame) = decoder.next_frame() {
            match frame {
                Ok(message) => dispatch(message, &pending, &notifications),
                Err(error) => frame_errors
                    .lock()
                    .expect("frame errors")
                    .push(error.to_string()),
            }
        }
    }

    // Mark closed before draining, so a call registering concurrently is caught by one or the
    // other and never waits out its timeout on a transport that is already gone.
    closed.store(true, Ordering::SeqCst);
    for (_, sender) in pending.lock().expect("pending").drain() {
        drop(sender);
    }
}

fn dispatch(message: Value, pending: &Pending, notifications: &broadcast::Sender<Notification>) {
    let Some(object) = message.as_object() else {
        return;
    };

    if let Some(id) = object.get("id").and_then(Value::as_u64) {
        let Some(sender) = pending.lock().expect("pending").remove(&id) else {
            return;
        };
        let outcome = if let Some(error) = object.get("error") {
            Err(RpcFailure {
                code: error.get("code").and_then(Value::as_i64).unwrap_or(0),
                message: error
                    .get("message")
                    .and_then(Value::as_str)
                    .unwrap_or("engine reported an error without a message")
                    .to_owned(),
            })
        } else if let Some(result) = object.get("result") {
            Ok(result.clone())
        } else {
            Err(RpcFailure {
                code: 0,
                message: "response carried neither result nor error".to_owned(),
            })
        };
        let _ = sender.send(outcome);
        return;
    }

    if let Some(method) = object.get("method").and_then(Value::as_str) {
        let _ = notifications.send(Notification {
            method: method.to_owned(),
            params: object.get("params").cloned().unwrap_or(Value::Null),
        });
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tokio::io::{duplex, AsyncBufReadExt, BufReader, DuplexStream};

    const TEST_TIMEOUT: Duration = Duration::from_millis(500);

    /// One scripted peer over in-memory pipes, so transport behaviour is tested without a process.
    struct Peer {
        requests: BufReader<DuplexStream>,
        responses: DuplexStream,
    }

    impl Peer {
        async fn next_request(&mut self) -> Value {
            let mut line = String::new();
            self.requests.read_line(&mut line).await.expect("request");
            serde_json::from_str(&line).expect("request is one JSON line")
        }

        async fn send(&mut self, message: Value) {
            self.responses
                .write_all(&encode(&message))
                .await
                .expect("send");
        }

        async fn send_raw(&mut self, bytes: &[u8]) {
            self.responses.write_all(bytes).await.expect("send raw");
        }
    }

    fn connect(timeout: Duration) -> (McpClient, Peer) {
        let (client_writes, peer_reads) = duplex(64 * 1024);
        let (peer_writes, client_reads) = duplex(64 * 1024);
        let client = McpClient::connect(client_reads, client_writes, timeout);
        (
            client,
            Peer {
                requests: BufReader::new(peer_reads),
                responses: peer_writes,
            },
        )
    }

    #[tokio::test]
    async fn routes_each_response_to_its_own_request_even_when_answered_out_of_order() {
        let (client, mut peer) = connect(TEST_TIMEOUT);

        let slow = client.call("layer_tree", json!({}));
        let fast = client.call("engine_handshake", json!({}));

        let peer_work = async {
            let first = peer.next_request().await;
            let second = peer.next_request().await;
            peer.send(json!({"jsonrpc": "2.0", "id": second["id"], "result": {"who": "second"}}))
                .await;
            peer.send(json!({"jsonrpc": "2.0", "id": first["id"], "result": {"who": "first"}}))
                .await;
        };

        let (slow, fast, ()) = tokio::join!(slow, fast, peer_work);
        assert_eq!(slow.expect("slow")["who"], "first");
        assert_eq!(fast.expect("fast")["who"], "second");
    }

    #[tokio::test]
    async fn surfaces_a_json_rpc_error_with_its_code_and_message() {
        let (client, mut peer) = connect(TEST_TIMEOUT);

        let call = client.call("open_project", json!({"path": "/missing"}));
        let peer_work = async {
            let request = peer.next_request().await;
            peer.send(json!({
                "jsonrpc": "2.0",
                "id": request["id"],
                "error": {"code": -32_002, "message": "project not found"},
            }))
            .await;
        };

        let (result, ()) = tokio::join!(call, peer_work);
        let error = result.expect_err("engine rejected the call");
        assert!(matches!(
            error,
            EngineError::Rpc { code: -32_002, ref message, .. } if message == "project not found"
        ));
    }

    #[tokio::test]
    async fn publishes_server_initiated_notifications_to_subscribers() {
        let (client, mut peer) = connect(TEST_TIMEOUT);
        let mut notifications = client.notifications();

        peer.send(
            json!({"jsonrpc": "2.0", "method": "notifications/progress", "params": {"n": 1}}),
        )
        .await;

        let notification = notifications.recv().await.expect("notification");
        assert_eq!(notification.method, "notifications/progress");
        assert_eq!(notification.params["n"], 1);
    }

    #[tokio::test]
    async fn stops_waiting_when_the_engine_never_answers() {
        let (client, _peer) = connect(Duration::from_millis(20));

        let error = client
            .call("render_project", json!({}))
            .await
            .expect_err("call timed out");

        assert!(
            matches!(error, EngineError::Timeout { ref method, .. } if method == "render_project")
        );
    }

    #[tokio::test]
    async fn fails_an_outstanding_call_when_the_transport_closes() {
        let (client, peer) = connect(TEST_TIMEOUT);
        let call = tokio::spawn(async move { client.call("project_snapshot", json!({})).await });

        drop(peer);

        let error = call.await.expect("join").expect_err("transport closed");
        assert!(matches!(error, EngineError::Closed(ref method) if method == "project_snapshot"));
    }

    #[tokio::test]
    async fn records_a_malformed_frame_and_still_answers_the_next_request() {
        let (client, mut peer) = connect(TEST_TIMEOUT);

        let call = client.call("engine_handshake", json!({}));
        let peer_work = async {
            let request = peer.next_request().await;
            peer.send_raw(b"this line is not json\n").await;
            peer.send(json!({"jsonrpc": "2.0", "id": request["id"], "result": {"ok": true}}))
                .await;
        };

        let (result, ()) = tokio::join!(call, peer_work);
        assert_eq!(result.expect("result")["ok"], true);
        assert_eq!(client.frame_errors().len(), 1);
    }

    #[tokio::test]
    async fn writes_concurrent_requests_as_whole_frames() {
        let (client, mut peer) = connect(TEST_TIMEOUT);
        let client = Arc::new(client);

        let calls: Vec<_> = (0..8)
            .map(|index| {
                let client = Arc::clone(&client);
                tokio::spawn(async move { client.call("noop", json!({ "index": index })).await })
            })
            .collect();

        let mut seen = Vec::new();
        for _ in 0..8 {
            let request = peer.next_request().await;
            assert_eq!(request["jsonrpc"], JSON_RPC_VERSION);
            seen.push(request["params"]["index"].as_u64().expect("index"));
            peer.send(json!({"jsonrpc": "2.0", "id": request["id"], "result": {}}))
                .await;
        }
        for call in calls {
            call.await.expect("join").expect("result");
        }

        seen.sort_unstable();
        assert_eq!(seen, (0..8).collect::<Vec<_>>());
    }
}

//! Newline-delimited JSON framing, the wire format of the MCP stdio transport.
//!
//! A sidecar writes one JSON message per line. Reads arrive in arbitrary chunks, so the decoder
//! keeps a buffer across reads and yields only whole frames. A malformed line is reported and
//! discarded rather than poisoning the stream: the next line still decodes.

use serde_json::Value;

/// Refuse a line larger than this rather than growing the buffer without bound.
pub const MAX_FRAME_BYTES: usize = 16 * 1024 * 1024;

#[derive(Debug, thiserror::Error, PartialEq, Eq)]
pub enum FrameError {
    #[error("engine frame exceeded {MAX_FRAME_BYTES} bytes and was discarded")]
    TooLong,
    #[error("engine frame was not valid JSON: {0}")]
    NotJson(String),
    #[error("engine frame was not valid UTF-8")]
    NotUtf8,
}

/// Accumulates sidecar stdout bytes and hands back one decoded frame at a time.
#[derive(Debug, Default)]
pub struct FrameDecoder {
    buffer: Vec<u8>,
    overlong: bool,
}

impl FrameDecoder {
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    /// Append a chunk of however many bytes the operating system happened to deliver.
    pub fn push(&mut self, chunk: &[u8]) {
        self.buffer.extend_from_slice(chunk);
    }

    /// Whether a partial frame is still waiting for its terminating newline.
    #[must_use]
    pub fn has_partial_frame(&self) -> bool {
        !self.buffer.is_empty()
    }

    /// Pop the next complete frame, or `None` while the current line is still incomplete.
    pub fn next_frame(&mut self) -> Option<Result<Value, FrameError>> {
        loop {
            let Some(newline) = self.buffer.iter().position(|byte| *byte == b'\n') else {
                if self.buffer.len() > MAX_FRAME_BYTES {
                    // Drop the runaway bytes now; the rest of the line is skipped as it arrives.
                    self.buffer.clear();
                    self.overlong = true;
                    return Some(Err(FrameError::TooLong));
                }
                return None;
            };

            let mut line: Vec<u8> = self.buffer.drain(..=newline).collect();
            line.pop();
            if line.last() == Some(&b'\r') {
                line.pop();
            }

            if self.overlong {
                // The tail of a frame already reported as too long carries no usable message.
                self.overlong = false;
                continue;
            }
            if line.iter().all(u8::is_ascii_whitespace) {
                continue;
            }
            return Some(decode(&line));
        }
    }
}

fn decode(line: &[u8]) -> Result<Value, FrameError> {
    let text = std::str::from_utf8(line).map_err(|_| FrameError::NotUtf8)?;
    serde_json::from_str(text).map_err(|error| FrameError::NotJson(error.to_string()))
}

/// Encode one message as the transport expects it: compact JSON plus a single newline.
#[must_use]
pub fn encode(message: &Value) -> Vec<u8> {
    let mut bytes = serde_json::to_vec(message).unwrap_or_else(|_| b"{}".to_vec());
    bytes.push(b'\n');
    bytes
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn decodes_one_frame_per_line() {
        let mut decoder = FrameDecoder::new();
        decoder.push(b"{\"id\":1}\n{\"id\":2}\n");

        assert_eq!(decoder.next_frame(), Some(Ok(json!({"id": 1}))));
        assert_eq!(decoder.next_frame(), Some(Ok(json!({"id": 2}))));
        assert_eq!(decoder.next_frame(), None);
    }

    #[test]
    fn withholds_a_frame_split_across_reads_until_its_newline_arrives() {
        let mut decoder = FrameDecoder::new();
        decoder.push(b"{\"id\"");

        assert_eq!(decoder.next_frame(), None);
        assert!(decoder.has_partial_frame());

        decoder.push(b":7}\n");
        assert_eq!(decoder.next_frame(), Some(Ok(json!({"id": 7}))));
        assert!(!decoder.has_partial_frame());
    }

    #[test]
    fn reports_a_malformed_line_and_keeps_decoding_the_next_one() {
        let mut decoder = FrameDecoder::new();
        decoder.push(b"not json\n{\"id\":3}\n");

        assert!(matches!(
            decoder.next_frame(),
            Some(Err(FrameError::NotJson(_)))
        ));
        assert_eq!(decoder.next_frame(), Some(Ok(json!({"id": 3}))));
    }

    #[test]
    fn tolerates_carriage_returns_and_blank_lines() {
        let mut decoder = FrameDecoder::new();
        decoder.push(b"\r\n{\"ok\":true}\r\n\n");

        assert_eq!(decoder.next_frame(), Some(Ok(json!({"ok": true}))));
        assert_eq!(decoder.next_frame(), None);
    }

    #[test]
    fn discards_an_overlong_frame_without_growing_without_bound() {
        let mut decoder = FrameDecoder::new();
        decoder.push(&vec![b'x'; MAX_FRAME_BYTES + 1]);

        assert_eq!(decoder.next_frame(), Some(Err(FrameError::TooLong)));

        decoder.push(b"more of the runaway line\n{\"id\":9}\n");
        assert_eq!(decoder.next_frame(), Some(Ok(json!({"id": 9}))));
    }

    #[test]
    fn rejects_a_frame_that_is_not_utf8() {
        let mut decoder = FrameDecoder::new();
        decoder.push(&[0xff, 0xfe, b'\n']);

        assert_eq!(decoder.next_frame(), Some(Err(FrameError::NotUtf8)));
    }

    #[test]
    fn encodes_exactly_one_newline_terminated_line() {
        assert_eq!(encode(&json!({"a": 1})), b"{\"a\":1}\n".to_vec());
    }
}

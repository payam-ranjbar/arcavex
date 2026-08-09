//! The private MCP sidecar: framing, JSON-RPC correlation, and lifecycle supervision.

pub mod client;
pub mod framing;
pub mod supervisor;

pub use client::{EngineError, McpClient, Notification};
pub use framing::{encode, FrameDecoder, FrameError, MAX_FRAME_BYTES};
pub use supervisor::{
    restart_delay, sha256_file, CommandLauncher, EngineHandle, EngineLauncher, EngineLock,
    EngineSpec, EngineState, EngineStatus, EngineStreams, LaunchedEngine, LockedArtifact,
    StartupError, Supervisor, CRASH_LOOP_THRESHOLD, MAX_RESTART_DELAY, MCP_PROTOCOL_VERSION,
    STDERR_TAIL_LINES,
};

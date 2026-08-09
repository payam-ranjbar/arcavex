//! Render scheduling: one active target, latest wins, last good picture retained.

pub mod scheduler;

pub use scheduler::{
    Completion, RenderJob, RenderKey, RenderOutput, RenderScheduler, RenderState, RenderStatus,
};

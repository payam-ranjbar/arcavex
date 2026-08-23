//! One active target, latest wins, and the last good picture stays on screen.
//!
//! Rendering is slow enough that a burst of edits would otherwise queue a backlog the user has
//! already invalidated. The scheduler keeps at most one job in flight and at most one queued, and
//! publishes a result only when its key is still the one the workbench is asking for.

use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};
use serde_json::Value;

/// Everything that makes one rendered picture different from another.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct RenderKey {
    /// The engine's render revision: changes only when render-affecting inputs change.
    pub render_revision: String,
    pub format: Option<String>,
    pub locale: Option<String>,
    /// Render options that change the output, kept ordered so the key is stable.
    pub options: BTreeMap<String, String>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum RenderState {
    Idle,
    Rendering,
    Current,
    Stale,
    Failed,
}

/// A successful render, kept as the last good picture until a newer one succeeds.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct RenderOutput {
    pub key: RenderKey,
    pub image_url: String,
    /// Where the engine actually wrote this picture. Saving copies this file rather than
    /// re-rendering, so what lands on disk is the proof that was on screen.
    pub source_path: String,
    pub width_px: u32,
    pub height_px: u32,
    pub content_sha256: Option<String>,
    pub compile_ms: Option<u64>,
    pub render_ms: Option<u64>,
}

/// A job handed to the engine. The id is what makes a stale completion identifiable.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct RenderJob {
    pub id: u64,
    pub key: RenderKey,
}

/// What the scheduler decided a completion meant.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Completion {
    /// The result is current and was published.
    Published,
    /// The result arrived for a key nobody wants any more and was dropped.
    Discarded,
    /// The render failed; the last good picture stays visible and is marked stale.
    Failed,
}

/// The state the workbench renders, mirroring the frontend `RenderStatus` port.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct RenderStatus {
    pub state: RenderState,
    pub key: Option<RenderKey>,
    pub last_good: Option<RenderOutput>,
    pub job_id: Option<u64>,
    pub diagnostics: Vec<Value>,
}

/// Latest-wins queue for exactly one active target.
#[derive(Debug)]
pub struct RenderScheduler {
    desired: Option<RenderKey>,
    active: Option<RenderJob>,
    queued: Option<RenderKey>,
    last_good: Option<RenderOutput>,
    state: RenderState,
    diagnostics: Vec<Value>,
    next_id: u64,
}

impl Default for RenderScheduler {
    fn default() -> Self {
        Self::new()
    }
}

impl RenderScheduler {
    #[must_use]
    pub fn new() -> Self {
        Self {
            desired: None,
            active: None,
            queued: None,
            last_good: None,
            state: RenderState::Idle,
            diagnostics: Vec::new(),
            next_id: 1,
        }
    }

    #[must_use]
    pub fn status(&self) -> RenderStatus {
        RenderStatus {
            state: self.state,
            key: self.desired.clone(),
            last_good: self.last_good.clone(),
            job_id: self.active.as_ref().map(|job| job.id),
            diagnostics: self.diagnostics.clone(),
        }
    }

    /// Ask for a picture. Returns the job to start now, or `None` when one is already running.
    ///
    /// A second request while a job is in flight replaces whatever was queued: the user only
    /// ever wants the newest one.
    pub fn request(&mut self, key: RenderKey) -> Option<RenderJob> {
        self.desired = Some(key.clone());
        if self.active.is_some() {
            self.queued = Some(key);
            return None;
        }
        Some(self.start(key))
    }

    /// Report a finished job. Returns what happened and the next job to start, if any.
    pub fn complete(
        &mut self,
        job: &RenderJob,
        outcome: Result<RenderOutput, Vec<Value>>,
    ) -> (Completion, Option<RenderJob>) {
        let was_active = self
            .active
            .as_ref()
            .is_some_and(|active| active.id == job.id);
        if was_active {
            self.active = None;
        }

        let completion = if !was_active || self.desired.as_ref() != Some(&job.key) {
            // The world moved on while this render ran; publishing it would show the past.
            Completion::Discarded
        } else {
            match outcome {
                Ok(output) => {
                    self.last_good = Some(output);
                    self.diagnostics.clear();
                    self.state = RenderState::Current;
                    Completion::Published
                }
                Err(diagnostics) => {
                    self.diagnostics = diagnostics;
                    self.state = RenderState::Failed;
                    Completion::Failed
                }
            }
        };

        let next = self.queued.take().map(|key| self.start(key));
        if next.is_none() && completion == Completion::Discarded && self.desired.is_some() {
            self.state = RenderState::Stale;
        }
        (completion, next)
    }

    /// The active target changed: the picture on screen is now for the wrong target.
    pub fn target_changed(&mut self) {
        self.active = None;
        self.queued = None;
        self.state = if self.last_good.is_some() {
            RenderState::Stale
        } else {
            RenderState::Idle
        };
    }

    /// The sidecar restarted: nothing in flight can still complete, but the picture survives.
    pub fn engine_restarted(&mut self) {
        self.active = None;
        // The newest request is worth retrying once the engine is ready again.
        self.queued = self.desired.clone();
        self.state = if self.last_good.is_some() {
            RenderState::Stale
        } else {
            RenderState::Idle
        };
    }

    /// Start whatever is queued, used once the engine reports ready again.
    pub fn resume(&mut self) -> Option<RenderJob> {
        if self.active.is_some() {
            return None;
        }
        self.queued.take().map(|key| self.start(key))
    }

    fn start(&mut self, key: RenderKey) -> RenderJob {
        let job = RenderJob {
            id: self.next_id,
            key,
        };
        self.next_id += 1;
        self.active = Some(job.clone());
        self.state = RenderState::Rendering;
        job
    }
}

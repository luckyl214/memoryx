from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from memoryx.learning.engine import LearningEngine
from memoryx.learning.artifacts import StudyArtifactBuilder
from memoryx.skills.distiller import MemoryXSkillDistiller


def _db_path() -> str:
    return os.getenv("MEMORYX_DB_PATH", "data/memoryx.db")


router = APIRouter(prefix="/v1/learning", tags=["learning"])


class EnsureProjectRequest(BaseModel):
    project_id: str
    name: str
    objective: str
    owner: str = "Drew"
    metadata: dict[str, Any] = {}


@router.post("/project/ensure")
async def ensure_project(req: EnsureProjectRequest):
    engine = LearningEngine(_db_path())
    engine.ensure_project(
        project_id=req.project_id,
        name=req.name,
        objective=req.objective,
        owner=req.owner,
        metadata=req.metadata,
    )
    return {"ok": True, "project_id": req.project_id}


class StartLearningSessionRequest(BaseModel):
    project_id: str
    session_id: str
    title: str
    topic: str
    goal: str
    mastery_target: str = "会用"
    metadata: dict[str, Any] = {}


@router.post("/session/start")
async def start_learning_session(req: StartLearningSessionRequest):
    engine = LearningEngine(_db_path())
    result = engine.start_session(**req.model_dump())
    return {
        "learning_session_id": result.learning_session_id,
        "project_id": result.project_id,
        "session_id": result.session_id,
        "status": result.status,
    }


class EndLearningSessionRequest(BaseModel):
    session_id: str
    summary: str
    artifacts: list[dict[str, Any]] = []


@router.post("/session/end")
async def end_learning_session(req: EndLearningSessionRequest):
    engine = LearningEngine(_db_path())
    return engine.end_session(
        session_id=req.session_id,
        summary=req.summary,
        artifacts=req.artifacts,
    )


class MasteryCheckRequest(BaseModel):
    project_id: str
    session_id: str
    topic: str
    level: str
    evidence: list[str]
    weak_points: list[str]
    next_tasks: list[str]
    score: float


@router.post("/mastery/check")
async def mastery_check(req: MasteryCheckRequest):
    engine = LearningEngine(_db_path())
    check_id = engine.record_mastery_check(**req.model_dump())
    return {"ok": True, "mastery_check_id": check_id}


@router.get("/project/{project_id}/progress")
async def project_progress(project_id: str):
    engine = LearningEngine(_db_path())
    return engine.get_project_progress(project_id=project_id)


class WriteReviewRequest(BaseModel):
    root: str = os.getenv("MEMORYX_ROOT", "data")
    project_id: str
    topic: str
    goal: str
    learned: list[str] = []
    unclear: list[str] = []
    mistakes: list[str] = []
    reusable_methods: list[str] = []
    next_actions: list[str] = []


@router.post("/artifact/session-review")
async def write_session_review(req: WriteReviewRequest):
    builder = StudyArtifactBuilder(req.root)
    path = builder.append_session_review(
        project_id=req.project_id,
        topic=req.topic,
        goal=req.goal,
        learned=req.learned,
        unclear=req.unclear,
        mistakes=req.mistakes,
        reusable_methods=req.reusable_methods,
        next_actions=req.next_actions,
    )
    return {"ok": True, "path": str(path)}


distill_router = APIRouter(prefix="/v1/skills", tags=["skills"])


@distill_router.post("/distill/recent")
async def distill_recent(since_hours: int = 24):
    distiller = MemoryXSkillDistiller(_db_path())
    atoms = distiller.extract_atoms_from_recent_sessions(since_hours=since_hours)
    n_atoms = distiller.persist_atoms(atoms)
    n_candidates = distiller.route_atoms_to_candidates(atoms)
    draft_ids = distiller.build_skill_drafts()
    return {
        "ok": True,
        "atoms": n_atoms,
        "candidates": n_candidates,
        "draft_ids": draft_ids,
    }


class ApproveDraftRequest(BaseModel):
    draft_id: str
    hermes_skill_dir: str = os.getenv("HERMES_SKILL_DIR", os.path.expanduser("~/.hermes/skills"))


@distill_router.post("/draft/approve")
async def approve_draft(req: ApproveDraftRequest):
    distiller = MemoryXSkillDistiller(_db_path())
    path = distiller.approve_draft(
        draft_id=req.draft_id,
        hermes_skill_dir=req.hermes_skill_dir,
    )
    return {"ok": True, "installed_path": str(path)}
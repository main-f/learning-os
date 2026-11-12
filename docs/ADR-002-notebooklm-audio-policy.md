# ADR-002 — NotebookLM audio policy

Status: accepted for v0.3 (2026-11-12)

## Decision

NotebookLM is the preferred producer for course podcasts. The user has already tested ordinary TTS `.m4a` output and found its quality very poor. Therefore, unless the user gives explicit future approval, Learning OS must not implement, enable, or silently select a TTS fallback.

If NotebookLM fails, the allowed fallback is a verified text script plus questions, or the most recent still-usable NotebookLM episode. Audio generation, delivery, and playback must remain separate from Mastery and Official grade.

This milestone does not call NotebookLM, automate Google login, or read/store Google tokens or cookies. Those capabilities require a separate approved implementation and private credential design.


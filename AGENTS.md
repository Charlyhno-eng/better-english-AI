# AGENTS.md

## Project Overview

An AI-powered English learning application focused on conversational practice, pronunciation, accent, grammar, and writing. Users can have spoken conversations in English with an AI, receive corrections, and improve their English over time.

## Tech Stack

Backend: Python, FastAPI, GLM 5.3 Flash for conversation and corrections, Parakeet TDT 0.6B v3 for Speech-to-Text, Pocket TTS for Text-to-Speech, OpenPronounce for pronunciation and phoneme analysis, and eSpeak NG for phoneme generation.

Frontend: React, React Router, TypeScript.

## Constraints

All local AI components must run on CPU. No GPU is required. No paid services other than the GLM API. Prefer open-source and locally runnable solutions. Keep the architecture simple, modular, and easy to replace.

Parakeet and Pocket TTS do not necessarily need to be installed locally. Using their Hugging Face implementations/models is acceptable when practical.

## Existing Reference Project

An existing project already integrates Parakeet TDT 0.6B v3, Pocket TTS, and GLM and should be inspected before implementing these integrations. Reuse relevant approaches and existing knowledge where appropriate instead of rebuilding them from scratch.

Reference project: `/home/charly/Documents/Projets/1.OSEF/T.A.R.S./`

## High-Level Architecture

Project
├── backend
│   ├── API
│   ├── AI / Speech
│   └── Core
│
├── frontend
│   ├── Pages
│   ├── Components
│   └── Features
│
└── shared

## Core Flow

User speech is transcribed with Parakeet, analyzed for pronunciation with OpenPronounce, processed by GLM for conversation and corrections, and answered using Pocket TTS.

## Development Principles

Follow existing project conventions and keep changes focused. Avoid unnecessary dependencies and do not introduce GPU-only solutions. Prioritize low latency for voice conversations. Keep components independent and easy to replace. Before implementing Parakeet, Pocket TTS, or GLM integrations, inspect the existing reference project and reuse proven patterns when appropriate.

## Working Rules

Update this file only when lasting project guidance changes.

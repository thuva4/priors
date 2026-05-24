from __future__ import annotations

from datetime import date as date_cls


def editor_template(today: date_cls | None = None) -> str:
    d = (today or date_cls.today()).isoformat()
    return f"""---
id:
date: {d}
source: human
trigger: ""
rule: ""
tags: []
severity: misleading
scope: project
stacks: []
---

## What happened

## Why it's wrong

## How to spot it
"""

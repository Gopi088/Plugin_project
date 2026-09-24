#!/usr/bin/env python3
"""Compatibility entry point for the shared batch parser."""
from scripts.batch_parse import main, parse_resume_to_json as parse_resume
if __name__=='__main__':
    raise SystemExit(main())

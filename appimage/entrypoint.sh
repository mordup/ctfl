#!/bin/bash
# AppImage entrypoint for CTFL
{{ python-executable }} -m ctfl "$@"

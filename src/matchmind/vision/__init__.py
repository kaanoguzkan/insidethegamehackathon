"""Auto-eventing from video: a synthetic broadcast-style video feed, a model that reads it, and the tracking it gives back.

The simulator knows where every player is. To test the pipeline the way a studio would meet it (a video feed in, metrics out), :mod:`render` turns
tracking into top-down video frames, :mod:`detect` finds the players and the ball in the *pixels alone*, and :mod:`track` turns the detections back into
the tracking chunks the physical analyzer reads. The analyzer, the interpreter and the narrative stages then work from what the video model saw, not
from the simulator's truth. :mod:`evaluate` measures how close that is.
"""

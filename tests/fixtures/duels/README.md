# Saved replay regressions

Two real `duels-replay-v1` files copied from the existing local `duels_probe/`
workspace. Expected normalized outputs were copied from `duels_parsed/` and
gzip-compressed without changing their JSON contents. Original downloads and
outputs now live under `data/duels/` and are ignored by Git.

These fixtures include player names and the replay perspective's visible hand;
they represent the original replay data, not anonymized or synthetic games.
Tests check complete output parity, input immutability, undo invalidation and
the four ATTACK/CHALLENGE frames. They do not call the API or require a token.

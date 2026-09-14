"""One module per tab, one class per tab.

Each tab takes the shared `mtproc_gui.app.State` in its constructor and exposes a
`reload()` that rebuilds it from whatever survey `State` is now holding.
"""

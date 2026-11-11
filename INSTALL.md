# Plug-and-play install (from the zip, no GitHub needed)

```bash
# 1. Put the plugin where Hermes looks for user plugins
unzip a11y-lens.zip -d ~/.hermes/plugins/          # creates ~/.hermes/plugins/a11y-lens

# 2. Install its Python dependency into Hermes' environment, and validate
hermes plugins validate ~/.hermes/plugins/a11y-lens --install-deps

# 3. Enable it
hermes plugins enable a11y-lens

# 4. Browser (skip if Chrome/Edge is installed) + self-test
hermes a11y install
hermes a11y doctor
```

`hermes a11y doctor` launches the browser, runs axe against a probe page and must find a planted violation. If it prints `All good.`, the demo will work:

```bash
hermes a11y demo
hermes     # then: Audit ./a11y-lens-demo with A11Y Lens, fix the issues in the source, rescan, and prove it improved.
```

If `hermes plugins validate … --install-deps` is unavailable in your build, run `pip install "playwright>=1.48,<2"` in the same Python environment Hermes uses.

Windows: use `%USERPROFILE%\.hermes\plugins` instead of `~/.hermes/plugins`.

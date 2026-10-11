# Process walkthrough deck - how it was made

- `spec.js` (text of every step) and `gen.js` (pptxgenjs) build `docs/AIS_AssetTrack_Process_Walkthrough.pptx`.
- Screens were captured by running the HHT app in a phone-size browser (`expo export -p web`) against a demo server.
- `webshim/` holds the browser stand-ins used only for those screenshots (SQLite, secure store, camera/OCR sample).
  To reuse: copy `webshim/*.js` to `hht/.webshim/` and `metro.config.js.txt` to `hht/metro.config.js`.
  **Never leave them in `hht/` for an APK build.** Developed by DT

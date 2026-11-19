// Apply the saved theme before first paint (no light/dark flash). A file, not inline, so CSP can forbid inline scripts.
try {
  var t = localStorage.getItem("veyra-theme");
  var dark = t ? t === "dark" : window.matchMedia("(prefers-color-scheme: dark)").matches;
  if (dark) document.documentElement.classList.add("dark");
} catch (e) {}

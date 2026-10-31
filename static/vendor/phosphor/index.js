(function() {
  if (document.getElementById('phosphor-icons-css')) return;
  var head = document.getElementsByTagName("head")[0];
  var link = document.createElement("link");
  link.id = 'phosphor-icons-css';
  link.rel = "stylesheet";
  link.type = "text/css";
  link.href = "/static/vendor/phosphor/phosphor.css";
  head.appendChild(link);
})();

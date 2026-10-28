// Drag-and-drop and live preview for cover photo inputs.
// Progressive enhancement: the plain <input type="file"> works with JavaScript off.
(function () {
  function setup(zone) {
    var input = zone.querySelector('input[type="file"]');
    var preview = zone.querySelector(".cover-dropzone-preview");
    var current = zone.querySelector(".cover-dropzone-current");
    var icon = zone.querySelector(".cover-dropzone-icon");
    var text = zone.querySelector(".cover-dropzone-text");
    var filename = zone.querySelector(".cover-dropzone-filename");
    if (!input || !preview) return;

    function showFile(file) {
      if (!file || !file.type || file.type.indexOf("image/") !== 0) return;
      var reader = new FileReader();
      reader.onload = function (event) {
        preview.src = event.target.result;
        preview.classList.remove("hidden");
        if (current) current.classList.add("hidden");
        if (icon) icon.classList.add("hidden");
        if (filename) {
          filename.textContent = file.name;
          filename.classList.remove("hidden");
        }
        if (text) text.classList.add("hidden");
      };
      reader.readAsDataURL(file);
    }

    input.addEventListener("change", function () {
      if (input.files && input.files[0]) showFile(input.files[0]);
    });

    ["dragenter", "dragover"].forEach(function (name) {
      zone.addEventListener(name, function (event) {
        event.preventDefault();
        zone.classList.add("is-dragover");
      });
    });
    ["dragleave", "dragend", "drop"].forEach(function (name) {
      zone.addEventListener(name, function () {
        zone.classList.remove("is-dragover");
      });
    });
    zone.addEventListener("drop", function (event) {
      event.preventDefault();
      var files = event.dataTransfer && event.dataTransfer.files;
      if (!files || !files.length) return;
      input.files = files;
      showFile(files[0]);
    });
  }

  document.querySelectorAll("[data-cover-dropzone]").forEach(setup);
})();

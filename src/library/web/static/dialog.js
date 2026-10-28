// Generic opener/closer for native <dialog> popups.
// <button data-dialog-open="my-dialog"> opens #my-dialog; any element with
// data-dialog-close inside a dialog closes it (including the backdrop).
(function () {
  document.querySelectorAll("[data-dialog-open]").forEach(function (opener) {
    var dialog = document.getElementById(opener.dataset.dialogOpen);
    if (!dialog) return;
    opener.addEventListener("click", function () {
      dialog.showModal();
    });
  });

  document.querySelectorAll("dialog").forEach(function (dialog) {
    dialog.querySelectorAll("[data-dialog-close]").forEach(function (closer) {
      closer.addEventListener("click", function () {
        dialog.close();
      });
    });
    // Click on the backdrop (the dialog element itself, outside its content box) closes it.
    dialog.addEventListener("click", function (event) {
      if (event.target === dialog) dialog.close();
    });
  });
})();

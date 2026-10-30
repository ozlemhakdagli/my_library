document.addEventListener("change", function (event) {
  var box = event.target;
  if (!box.matches || !box.matches("[data-month-toggle]")) return;
  var input = box.closest("label").querySelector("[data-date-field]");
  var value = input.value || "";
  if (box.checked) {
    input.type = "month";
    input.value = value.length >= 7 ? value.slice(0, 7) : "";
  } else {
    input.type = "date";
    input.value = value.length === 7 ? "" : value;
  }
});

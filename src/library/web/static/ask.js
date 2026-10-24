// Streams /ask results into the live panel. Without JavaScript the plain form still works.
(function () {
  var form = document.querySelector("form[data-stream]");
  if (!form || !window.fetch || !window.ReadableStream) return;

  var live = document.getElementById("ask-live");
  var steps = document.getElementById("ask-steps");
  var thinking = document.getElementById("ask-thinking-text");
  var answer = document.getElementById("ask-answer");
  var books = document.getElementById("ask-books");
  var result = document.getElementById("ask-result");
  var button = form.querySelector("button[type=submit]");
  var current = null;

  function reset() {
    live.hidden = false;
    result.hidden = true;
    steps.textContent = "";
    thinking.textContent = "";
    answer.textContent = "";
    books.textContent = "";
    current = null;
    if (button) button.disabled = true;
  }

  function addStep(text) {
    if (current) current.classList.add("is-done");
    var item = document.createElement("li");
    item.className = "ask-step is-active";
    item.textContent = text;
    steps.appendChild(item);
    current = item;
  }

  function addError(text) {
    var item = document.createElement("li");
    item.className = "ask-step is-error";
    item.textContent = text;
    steps.appendChild(item);
  }

  function renderBooks(list) {
    books.textContent = "";
    list.forEach(function (book) {
      var item = document.createElement("li");
      item.className = "ask-book";
      var title = document.createElement("a");
      title.href = "/books/" + book.id;
      title.textContent = book.title;
      var meta = document.createElement("span");
      meta.className = "ask-book-meta";
      meta.textContent = book.authors.join(", ");
      item.appendChild(title);
      item.appendChild(meta);
      books.appendChild(item);
    });
  }

  function handle(block) {
    var name = "message";
    var data = "";
    block.split("\n").forEach(function (line) {
      if (line.indexOf("event:") === 0) name = line.slice(6).trim();
      else if (line.indexOf("data:") === 0) data += line.slice(5).trim();
    });
    if (!data) return;
    var payload = JSON.parse(data);
    if (name === "step") addStep(payload);
    else if (name === "thinking") { thinking.textContent += payload; }
    else if (name === "answer") { answer.textContent += payload; }
    else if (name === "books") renderBooks(payload);
    else if (name === "error") addError(payload);
    else if (name === "done") {
      if (current) current.classList.add("is-done");
      if (button) button.disabled = false;
    }
  }

  form.addEventListener("submit", async function (event) {
    event.preventDefault();
    reset();
    try {
      var response = await fetch(form.dataset.stream, { method: "POST", body: new FormData(form) });
      if (!response.ok || !response.body) throw new Error("bad response");
      var reader = response.body.getReader();
      var decoder = new TextDecoder();
      var buffer = "";
      while (true) {
        var chunk = await reader.read();
        if (chunk.done) break;
        buffer += decoder.decode(chunk.value, { stream: true });
        var blocks = buffer.split("\n\n");
        buffer = blocks.pop();
        blocks.forEach(handle);
      }
      if (buffer.trim()) handle(buffer);
    } catch (error) {
      addError(form.dataset.failed || "Request failed.");
    } finally {
      if (button) button.disabled = false;
    }
  });
})();

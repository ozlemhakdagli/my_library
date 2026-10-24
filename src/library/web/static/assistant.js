// Floating library assistant: chat bubbles, Enter to send, streamed replies from /ask/stream.
(function () {
  var toggle = document.getElementById("assistant-toggle");
  var panel = document.getElementById("assistant-panel");
  if (!toggle || !panel) return;

  var form = document.getElementById("assistant-form");
  var input = document.getElementById("assistant-input");
  var log = document.getElementById("assistant-log");
  var closeButton = document.getElementById("assistant-close");
  var sendButton = form.querySelector(".assistant-send");
  var endpoint = panel.dataset.endpoint;
  var failedText = panel.dataset.failed || "Request failed.";
  var busy = false;

  function open() {
    panel.hidden = false;
    toggle.setAttribute("aria-expanded", "true");
    input.focus();
  }

  function close() {
    panel.hidden = true;
    toggle.setAttribute("aria-expanded", "false");
    toggle.focus();
  }

  toggle.addEventListener("click", function () {
    if (panel.hidden) open(); else close();
  });
  closeButton.addEventListener("click", close);
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && !panel.hidden) close();
  });

  function scrollToEnd() {
    log.scrollTop = log.scrollHeight;
  }

  function bubble(role, text) {
    var item = document.createElement("div");
    item.className = "assistant-msg assistant-msg-" + role;
    if (text) item.textContent = text;
    log.appendChild(item);
    scrollToEnd();
    return item;
  }

  function appendStatus(container, text) {
    var line = document.createElement("div");
    line.className = "assistant-step";
    line.textContent = text;
    container.appendChild(line);
  }

  function thinkingBlock(container) {
    var details = document.createElement("details");
    details.className = "assistant-thinking";
    var summary = document.createElement("summary");
    summary.textContent = container.dataset.thinkingLabel || "Thinking";
    var pre = document.createElement("pre");
    details.appendChild(summary);
    details.appendChild(pre);
    container.appendChild(details);
    return pre;
  }

  function answerNode(container) {
    var node = document.createElement("div");
    node.className = "assistant-answer";
    container.appendChild(node);
    return node;
  }

  function tableFor(container, data) {
    var wrap = document.createElement("div");
    wrap.className = "assistant-table-wrap";
    var table = document.createElement("table");
    table.className = "assistant-table";
    var head = document.createElement("thead");
    var headRow = document.createElement("tr");
    data.headers.forEach(function (text) {
      var th = document.createElement("th");
      th.scope = "col";
      th.textContent = text;
      headRow.appendChild(th);
    });
    head.appendChild(headRow);
    table.appendChild(head);
    var body = document.createElement("tbody");
    data.rows.forEach(function (row) {
      var tr = document.createElement("tr");
      row.cells.forEach(function (cell, index) {
        var td = document.createElement("td");
        if (index === 0 && row.href) {
          var link = document.createElement("a");
          link.href = row.href;
          link.textContent = String(cell);
          td.appendChild(link);
        } else {
          td.textContent = String(cell);
        }
        tr.appendChild(td);
      });
      body.appendChild(tr);
    });
    table.appendChild(body);
    wrap.appendChild(table);
    container.appendChild(wrap);
  }

  function handle(block, state) {
    var name = "message";
    var data = "";
    block.split("\n").forEach(function (line) {
      if (line.indexOf("event:") === 0) name = line.slice(6).trim();
      else if (line.indexOf("data:") === 0) data += line.slice(5).trim();
    });
    if (!data) return;
    var payload = JSON.parse(data);
    if (name === "step") appendStatus(state.bubble, payload);
    else if (name === "thinking") {
      if (!state.thinking) state.thinking = thinkingBlock(state.bubble);
      state.thinking.textContent += payload;
      scrollToEnd();
    } else if (name === "answer") {
      if (!state.answer) state.answer = answerNode(state.bubble);
      state.answer.textContent += payload;
      scrollToEnd();
    } else if (name === "books") bookList(state.bubble, payload);
    else if (name === "error") appendStatus(state.bubble, payload);
  }

  async function ask(question) {
    busy = true;
    sendButton.disabled = true;
    bubble("user", question);
    var reply = bubble("assistant", "");
    reply.dataset.thinkingLabel = panel.dataset.thinkingLabel || "Thinking";
    var state = { bubble: reply, thinking: null, answer: null };
    try {
      var body = new FormData();
      body.append("question", question);
      var response = await fetch(endpoint, { method: "POST", body: body });
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
        blocks.forEach(function (b) { handle(b, state); });
      }
      if (buffer.trim()) handle(buffer, state);
    } catch (error) {
      appendStatus(reply, failedText);
    } finally {
      busy = false;
      sendButton.disabled = false;
      input.focus();
    }
  }

  function submit() {
    var question = input.value.trim();
    if (!question || busy) return;
    input.value = "";
    autoSize();
    ask(question);
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    submit();
  });

  input.addEventListener("keydown", function (event) {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      submit();
    }
  });

  function autoSize() {
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 140) + "px";
  }
  input.addEventListener("input", autoSize);
})();

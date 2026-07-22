// Progressive question submission: intercepts forms marked with
// `data-stream-url`, shows a blocking loading overlay with live status
// updates, and appends the server-rendered, citation-validated result
// once arbitration completes. Falls back to the form's normal HTMX
// submission if fetch/streaming is unavailable.
(function () {
    "use strict";

    function findOverlay(form) {
        var conversation = form.closest("#conversation");
        return conversation ? conversation.querySelector(".loading-overlay") : null;
    }

    function setStatus(overlay, message) {
        if (!overlay) return;
        var statusEl = overlay.querySelector(".loading-status");
        if (statusEl) {
            statusEl.textContent = message;
        }
    }

    function setBusy(form, busy) {
        var textarea = form.querySelector("textarea");
        var button = form.querySelector("button[type=submit]");
        if (textarea) textarea.disabled = busy;
        if (button) button.disabled = busy;
        form.setAttribute("aria-busy", busy ? "true" : "false");
        var overlay = findOverlay(form);
        if (overlay) {
            overlay.hidden = !busy;
        }
    }

    function showError(form, message) {
        var existing = form.querySelector(".error");
        if (existing) existing.remove();
        var error = document.createElement("p");
        error.className = "error";
        error.textContent = message;
        form.appendChild(error);
    }

    function clearError(form) {
        var existing = form.querySelector(".error");
        if (existing) existing.remove();
    }

    function formatTimestamps(root) {
        var times = root.querySelectorAll("time.message-time[datetime]");
        for (var i = 0; i < times.length; i++) {
            var el = times[i];
            var date = new Date(el.getAttribute("datetime"));
            if (!isNaN(date.getTime())) {
                el.textContent = date.toLocaleString();
            }
        }
    }

    async function handleStreamSubmit(form) {
        if (form.dataset.streaming === "true") {
            return;
        }
        var streamUrl = form.dataset.streamUrl;
        if (!streamUrl || typeof fetch !== "function" || !window.ReadableStream) {
            return false;
        }

        var textarea = form.querySelector("textarea");
        var question = textarea ? textarea.value : "";
        var overlay = findOverlay(form);
        // Capture the form data before disabling controls: disabled form
        // controls are excluded from FormData, so building this after
        // setBusy(form, true) would silently submit an empty question.
        var formData = new FormData(form);

        form.dataset.streaming = "true";
        clearError(form);
        setBusy(form, true);
        setStatus(overlay, "Searching the rulebook and FAQ");

        try {
            var response = await fetch(streamUrl, {
                method: "POST",
                body: formData,
                headers: { Accept: "application/x-ndjson" },
            });

            if (!response.ok && !response.body) {
                throw new Error("request failed");
            }

            var reader = response.body.getReader();
            var decoder = new TextDecoder();
            var buffer = "";
            var conversationId = form.dataset.conversationId;

            while (true) {
                var chunk = await reader.read();
                if (chunk.done) break;
                buffer += decoder.decode(chunk.value, { stream: true });

                var lines = buffer.split("\n");
                buffer = lines.pop();

                for (var i = 0; i < lines.length; i++) {
                    var line = lines[i].trim();
                    if (!line) continue;
                    var event;
                    try {
                        event = JSON.parse(line);
                    } catch (parseError) {
                        continue;
                    }

                    if (event.type === "status") {
                        setStatus(overlay, event.message);
                    } else if (event.type === "result") {
                        var messages = document.getElementById("messages");
                        if (messages) {
                            var wrapper = document.createElement("div");
                            wrapper.innerHTML = event.html;
                            while (wrapper.firstChild) {
                                messages.appendChild(wrapper.firstChild);
                            }
                            if (window.htmx) {
                                window.htmx.process(messages);
                            }
                            formatTimestamps(messages);
                        }
                        if (textarea) {
                            textarea.value = "";
                            textarea.placeholder = "Continue the conversation…";
                        }
                        var label = form.querySelector("label[for=question]");
                        if (label) label.remove();
                        if (event.title !== null) {
                            var conversationTitle = document.getElementById("conversation-title");
                            if (conversationTitle) conversationTitle.textContent = event.title;
                        }
                    } else if (event.type === "error") {
                        showError(form, event.message || "The Arbiter could not process that question.");
                    }
                }
            }
        } catch (networkError) {
            showError(form, "The Arbiter could not be reached. Please try again.");
        } finally {
            setBusy(form, false);
            delete form.dataset.streaming;
        }

        return true;
    }

    document.addEventListener("submit", function (event) {
        var form = event.target;
        if (!(form instanceof HTMLFormElement) || !form.dataset.streamUrl) {
            return;
        }
        event.preventDefault();
        handleStreamSubmit(form);
    });

    document.addEventListener("DOMContentLoaded", function () {
        formatTimestamps(document);
    });

    document.body.addEventListener("htmx:afterSwap", function (event) {
        formatTimestamps(event.target);
    });
})();

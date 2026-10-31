/**
 * StudyBuddy AI — Frontend Application Logic
 * Implements conversational UI, state management, secure DOM rendering,
 * and robust API communication with the Flask backend.
 */

(function () {
    "use strict";

    // Application State
    const state = {
        conversationId: null,
        isGenerating: false,
    };

    // DOM Elements
    const elements = {
        chatForm: document.getElementById("chat-form"),
        userInput: document.getElementById("user-input"),
        sendBtn: document.getElementById("send-btn"),
        newChatBtn: document.getElementById("new-chat-btn"),
        messagesArea: document.getElementById("messages-container"),
        messagesList: document.getElementById("messages-list"),
        emptyState: document.getElementById("empty-state"),
        typingIndicator: document.getElementById("typing-indicator"),
        statusPill: document.getElementById("status-pill"),
        statusText: document.querySelector("#status-pill .status-text"),
        convIdBadge: document.getElementById("conv-id-badge"),
        notificationBanner: document.getElementById("notification-banner"),
        bannerText: document.getElementById("banner-text"),
        bannerCloseBtn: document.getElementById("banner-close-btn"),
        suggestionChips: document.querySelectorAll(".suggestion-chip"),
    };

    /**
     * Generate a RFC4122 v4 compliant UUID for conversation isolation.
     * Uses crypto.randomUUID when available, with a standard fallback.
     */
    function generateUUID() {
        if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
            return crypto.randomUUID();
        }
        return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, function (c) {
            const r = (Math.random() * 16) | 0;
            const v = c === "x" ? r : (r & 0x3) | 0x8;
            return v.toString(16);
        });
    }

    /**
     * Format current time as HH:MM AM/PM
     */
    function formatTime() {
        const now = new Date();
        return now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    }

    /**
     * Initialize conversation session
     */
    function initSession(isNew = false) {
        state.conversationId = generateUUID();
        
        // Update session UI badge (showing truncated ID for clean layout)
        if (elements.convIdBadge) {
            elements.convIdBadge.textContent = `ID: ${state.conversationId.slice(0, 8)}...`;
            elements.convIdBadge.title = `Full Conversation ID: ${state.conversationId}`;
        }

        if (isNew) {
            elements.messagesList.innerHTML = "";
            elements.emptyState.classList.remove("hidden");
            hideNotification();
            setStatus("ready");
            if (elements.userInput) {
                elements.userInput.value = "";
                elements.userInput.style.height = "auto";
                elements.userInput.focus();
            }
        }
    }

    /**
     * Set system status indicator
     */
    function setStatus(status) {
        if (!elements.statusPill) return;

        elements.statusPill.classList.remove("busy", "error");
        if (status === "busy") {
            elements.statusPill.classList.add("busy");
            if (elements.statusText) elements.statusText.textContent = "Thinking...";
        } else if (status === "error") {
            elements.statusPill.classList.add("error");
            if (elements.statusText) elements.statusText.textContent = "Error";
        } else {
            if (elements.statusText) elements.statusText.textContent = "Ready";
        }
    }

    /**
     * Show notification alert banner
     */
    function showNotification(message, type = "error") {
        if (!elements.notificationBanner || !elements.bannerText) return;

        elements.notificationBanner.classList.remove("hidden", "warning");
        if (type === "warning") {
            elements.notificationBanner.classList.add("warning");
        }
        elements.bannerText.textContent = message;
    }

    /**
     * Hide notification banner
     */
    function hideNotification() {
        if (elements.notificationBanner) {
            elements.notificationBanner.classList.add("hidden");
        }
    }

    /**
     * Safely render message content into a DOM container using safe methods
     * (textContent, document.createElement). Protects against XSS attacks.
     * 
     * Supports:
     * - Fenced code blocks (```python ... ```)
     * - Paragraph breaks
     * - Inline code segments (`code`)
     */
    function renderSafeMessageContent(container, rawText) {
        // Regex to separate fenced code blocks from regular text
        const codeBlockRegex = /```([a-zA-Z0-9_\-#+]*)\n([\s\S]*?)```/g;
        let lastIndex = 0;
        let match;

        while ((match = codeBlockRegex.exec(rawText)) !== null) {
            const textBefore = rawText.slice(lastIndex, match.index);
            if (textBefore) {
                renderTextParagraphs(container, textBefore);
            }

            const lang = match[1] || "";
            const codeContent = match[2];

            const preElem = document.createElement("pre");
            if (lang) {
                preElem.setAttribute("data-lang", lang);
            }
            
            // Code header with language and copy button
            const codeHeader = document.createElement("div");
            codeHeader.className = "code-header";
            
            const langLabel = document.createElement("span");
            langLabel.className = "code-lang-label";
            langLabel.textContent = lang ? lang.toUpperCase() : "CODE";
            
            const copyBtn = document.createElement("button");
            copyBtn.type = "button";
            copyBtn.className = "code-copy-btn";
            copyBtn.textContent = "Copy";
            copyBtn.addEventListener("click", function () {
                navigator.clipboard.writeText(codeContent).then(() => {
                    copyBtn.textContent = "Copied!";
                    setTimeout(() => { copyBtn.textContent = "Copy"; }, 2000);
                }).catch(() => {
                    copyBtn.textContent = "Failed";
                });
            });

            codeHeader.appendChild(langLabel);
            codeHeader.appendChild(copyBtn);
            preElem.appendChild(codeHeader);

            const codeElem = document.createElement("code");
            codeElem.textContent = codeContent; // SAFE: sets text only
            preElem.appendChild(codeElem);
            container.appendChild(preElem);

            lastIndex = match.index + match[0].length;
        }

        const remainingText = rawText.slice(lastIndex);
        if (remainingText) {
            renderTextParagraphs(container, remainingText);
        }
    }

    /**
     * Render inline formatting (code, bold, italic) safely into a parent element
     */
    function renderInlineFormattedText(parent, text) {
        // Pattern matches: `inline code` OR **bold** OR *italic*
        const tokenRegex = /(`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*)/g;
        let lastPos = 0;
        let tokenMatch;

        while ((tokenMatch = tokenRegex.exec(text)) !== null) {
            const rawPrefix = text.slice(lastPos, tokenMatch.index);
            if (rawPrefix) {
                parent.appendChild(document.createTextNode(rawPrefix));
            }

            const token = tokenMatch[0];
            if (token.startsWith("`") && token.endsWith("`")) {
                const codeElem = document.createElement("code");
                codeElem.textContent = token.slice(1, -1);
                parent.appendChild(codeElem);
            } else if (token.startsWith("**") && token.endsWith("**")) {
                const strongElem = document.createElement("strong");
                strongElem.textContent = token.slice(2, -2);
                parent.appendChild(strongElem);
            } else if (token.startsWith("*") && token.endsWith("*")) {
                const emElem = document.createElement("em");
                emElem.textContent = token.slice(1, -1);
                parent.appendChild(emElem);
            }

            lastPos = tokenMatch.index + token.length;
        }

        const trailing = text.slice(lastPos);
        if (trailing) {
            parent.appendChild(document.createTextNode(trailing));
        }
    }

    /**
     * Helper to render text paragraphs, bullet points, and ordered lists
     */
    function renderTextParagraphs(container, text) {
        const blocks = text.split(/\n\s*\n/);
        for (const block of blocks) {
            const cleanBlock = block.trim();
            if (!cleanBlock) continue;

            const lines = cleanBlock.split("\n");
            
            // Check if this block is an unordered list
            if (lines.every(line => /^[-*]\s+/.test(line.trim()))) {
                const ul = document.createElement("ul");
                ul.className = "chat-list";
                for (const line of lines) {
                    const li = document.createElement("li");
                    const itemContent = line.trim().replace(/^[-*]\s+/, "");
                    renderInlineFormattedText(li, itemContent);
                    ul.appendChild(li);
                }
                container.appendChild(ul);
                continue;
            }

            // Check if this block is an ordered list
            if (lines.every(line => /^\d+\.\s+/.test(line.trim()))) {
                const ol = document.createElement("ol");
                ol.className = "chat-list";
                for (const line of lines) {
                    const li = document.createElement("li");
                    const itemContent = line.trim().replace(/^\d+\.\s+/, "");
                    renderInlineFormattedText(li, itemContent);
                    ol.appendChild(li);
                }
                container.appendChild(ol);
                continue;
            }

            // Standard Paragraph
            const pElem = document.createElement("p");
            renderInlineFormattedText(pElem, cleanBlock);
            container.appendChild(pElem);
        }
    }

    /**
     * Append a message bubble to the chat container
     */
    function appendMessage(role, text) {
        // Hide empty state greeting on first message
        if (elements.emptyState) {
            elements.emptyState.classList.add("hidden");
        }

        const messageItem = document.createElement("div");
        messageItem.className = `message-item ${role}`;

        // Avatar
        const avatar = document.createElement("div");
        avatar.className = `avatar ${role === "user" ? "user-avatar" : "ai-avatar"}`;
        avatar.textContent = role === "user" ? "You" : "AI";

        // Message Content Container
        const contentWrapper = document.createElement("div");
        contentWrapper.className = "message-content";

        // Message Bubble
        const bubble = document.createElement("div");
        bubble.className = "message-bubble";
        renderSafeMessageContent(bubble, text);

        // Meta (Timestamp and Role)
        const meta = document.createElement("div");
        meta.className = "message-meta";
        meta.textContent = `${role === "user" ? "You" : "StudyBuddy AI"} • ${formatTime()}`;

        contentWrapper.appendChild(bubble);
        contentWrapper.appendChild(meta);

        messageItem.appendChild(avatar);
        messageItem.appendChild(contentWrapper);

        elements.messagesList.appendChild(messageItem);
        scrollToBottom();
    }

    /**
     * Scroll the chat window to the newest message
     */
    function scrollToBottom() {
        if (!elements.messagesArea) return;
        requestAnimationFrame(() => {
            elements.messagesArea.scrollTop = elements.messagesArea.scrollHeight;
        });
    }

    /**
     * Set loading / generation state
     */
    function setGenerating(isGenerating) {
        state.isGenerating = isGenerating;
        if (elements.sendBtn) {
            elements.sendBtn.disabled = isGenerating;
        }
        if (elements.userInput) {
            elements.userInput.disabled = isGenerating;
        }
        if (elements.typingIndicator) {
            if (isGenerating) {
                elements.typingIndicator.classList.remove("hidden");
                scrollToBottom();
            } else {
                elements.typingIndicator.classList.add("hidden");
            }
        }
        setStatus(isGenerating ? "busy" : "ready");
    }

    /**
     * Send user message to the Flask /chat endpoint
     */
    async function sendMessage(messageText) {
        const text = (messageText || elements.userInput.value || "").trim();
        if (!text || state.isGenerating) return;

        hideNotification();

        // 1. Render User Message
        appendMessage("user", text);

        // 2. Clear input field and reset height
        elements.userInput.value = "";
        elements.userInput.style.height = "auto";

        // 3. Set loading state
        setGenerating(true);

        try {
            const response = await fetch("/chat", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify({
                    message: text,
                    conversation_id: state.conversationId,
                }),
            });

            const data = await response.json().catch(() => ({}));

            if (!response.ok) {
                const errorMsg = data.error || `Server responded with status ${response.status}.`;
                setStatus("error");
                showNotification(errorMsg, response.status === 503 ? "warning" : "error");

                // Render error notice in chat as well
                const errorCard = document.createElement("div");
                errorCard.className = "message-item ai";
                const avatar = document.createElement("div");
                avatar.className = "avatar ai-avatar";
                avatar.textContent = "AI";

                const content = document.createElement("div");
                content.className = "message-content";

                const bubble = document.createElement("div");
                bubble.className = "message-bubble";
                bubble.style.borderLeft = "4px solid var(--status-error)";
                
                const errTitle = document.createElement("p");
                errTitle.style.fontWeight = "600";
                errTitle.style.color = "var(--status-error)";
                errTitle.textContent = "⚠️ Unable to generate response";

                const errBody = document.createElement("p");
                errBody.textContent = errorMsg;

                bubble.appendChild(errTitle);
                bubble.appendChild(errBody);
                content.appendChild(bubble);
                errorCard.appendChild(avatar);
                errorCard.appendChild(content);

                elements.messagesList.appendChild(errorCard);
                scrollToBottom();
                return;
            }

            // Sync conversation ID returned from server
            if (data.conversation_id) {
                state.conversationId = data.conversation_id;
                if (elements.convIdBadge) {
                    elements.convIdBadge.textContent = `ID: ${state.conversationId.slice(0, 8)}...`;
                    elements.convIdBadge.title = `Full Conversation ID: ${state.conversationId}`;
                }
            }

            // Render AI response
            if (data.reply) {
                appendMessage("ai", data.reply);
            } else {
                showNotification("Empty response received from server.");
            }
        } catch (networkError) {
            console.error("Chat communication failure:", networkError);
            setStatus("error");
            showNotification(
                "Failed to communicate with StudyBuddy AI backend. Ensure the Flask server is running.",
                "error"
            );
        } finally {
            setGenerating(false);
            if (elements.userInput) {
                elements.userInput.focus();
            }
        }
    }

    /**
     * Auto-resize textarea to fit content up to maximum limit
     */
    function autoResizeTextarea() {
        if (!elements.userInput) return;
        elements.userInput.style.height = "auto";
        const newHeight = Math.min(elements.userInput.scrollHeight, 150);
        elements.userInput.style.height = `${Math.max(newHeight, 48)}px`;
    }

    /**
     * Event Listeners Registration
     */
    function registerEventListeners() {
        // Form submission
        if (elements.chatForm) {
            elements.chatForm.addEventListener("submit", function (e) {
                e.preventDefault();
                sendMessage();
            });
        }

        // Textarea keyboard handling: Enter sends, Shift+Enter new line
        if (elements.userInput) {
            elements.userInput.addEventListener("keydown", function (e) {
                if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    sendMessage();
                }
            });

            elements.userInput.addEventListener("input", autoResizeTextarea);
        }

        // New Chat Button
        if (elements.newChatBtn) {
            elements.newChatBtn.addEventListener("click", function () {
                initSession(true);
            });
        }

        // Suggestion Chips
        if (elements.suggestionChips) {
            elements.suggestionChips.forEach((chip) => {
                chip.addEventListener("click", function () {
                    const promptText = this.getAttribute("data-prompt");
                    if (promptText && !state.isGenerating) {
                        elements.userInput.value = promptText;
                        autoResizeTextarea();
                        sendMessage(promptText);
                    }
                });
            });
        }

        // Notification Banner Dismiss
        if (elements.bannerCloseBtn) {
            elements.bannerCloseBtn.addEventListener("click", hideNotification);
        }
    }

    // Initialize application when DOM is ready
    document.addEventListener("DOMContentLoaded", function () {
        initSession(false);
        registerEventListeners();
        if (elements.userInput) {
            elements.userInput.focus();
        }
    });
})();

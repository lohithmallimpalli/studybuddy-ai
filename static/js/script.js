/**
 * StudyBuddy AI — Professional Frontend Application Logic (v3.0)
 * Multi-user platform supporting Registered Accounts and Persistent Guest Access.
 * Features:
 * - Multi-user authentication & profile status display
 * - Guest mode with usage counter and seamless account upgrade modal (with chat transfer)
 * - Persistent SQLite conversation history & sidebar management
 * - Chronological date grouping (Today, Yesterday, Previous 7 Days, Older)
 * - Three-dot dropdown menu for Rename & Delete
 * - Real-time conversation search
 * - Collapsible desktop sidebar & mobile slide-out drawer
 * - Rich Markdown parsing with code copy & syntax tokenization
 * - Safe XSS prevention using native DOM methods
 * - Copy response & Regenerate response support
 * - Generation abort / stop controller
 * - Light / Dark theme toggle with localStorage persistence
 */

(function () {
    "use strict";

    // ---------------------------------------------------------------------------
    // Application State
    // ---------------------------------------------------------------------------
    const state = {
        currentUser: null,       // { id, name, email, is_guest, guest_message_count, guest_limit }
        conversationId: null,
        conversationTitle: "New Study Session",
        conversations: [],       // Array of { id, title, created_at, updated_at, message_count, last_message }
        messages: [],            // Messages in active conversation
        isGenerating: false,
        activeAbortController: null,
        searchQuery: "",
        theme: "dark",
        dropdownTargetId: null,
        renameTargetId: null,
        deleteTargetId: null,
    };

    // ---------------------------------------------------------------------------
    // DOM Element References
    // ---------------------------------------------------------------------------
    const elements = {
        appLayout: document.getElementById("app-layout"),
        sidebar: document.getElementById("sidebar"),
        sidebarBackdrop: document.getElementById("sidebar-backdrop"),
        sidebarCollapseBtn: document.getElementById("sidebar-collapse-btn"),
        desktopExpandBtn: document.getElementById("desktop-expand-btn"),
        mobileMenuBtn: document.getElementById("mobile-menu-btn"),
        sidebarNewChatBtn: document.getElementById("sidebar-new-chat-btn"),
        headerNewChatBtn: document.getElementById("header-new-chat-btn"),
        historySearchInput: document.getElementById("history-search-input"),
        searchClearBtn: document.getElementById("search-clear-btn"),
        historyList: document.getElementById("history-list"),
        historyEmptyState: document.getElementById("history-empty-state"),
        themeToggleBtn: document.getElementById("theme-toggle-btn"),
        themeLabel: document.getElementById("theme-label"),
        clearAllBtn: document.getElementById("clear-all-btn"),
        
        activeConvTitle: document.getElementById("active-conv-title"),
        titleText: document.getElementById("title-text"),
        statusPill: document.getElementById("status-pill"),
        statusText: document.querySelector("#status-pill .status-text"),
        
        notificationBanner: document.getElementById("notification-banner"),
        bannerText: document.getElementById("banner-text"),
        bannerCloseBtn: document.getElementById("banner-close-btn"),
        
        messagesArea: document.getElementById("messages-container"),
        messagesList: document.getElementById("messages-list"),
        welcomeScreen: document.getElementById("welcome-screen"),
        suggestionCards: document.querySelectorAll(".suggestion-card"),
        typingIndicator: document.getElementById("typing-indicator"),
        
        chatForm: document.getElementById("chat-form"),
        userInput: document.getElementById("user-input"),
        sendBtn: document.getElementById("send-btn"),
        stopBtn: document.getElementById("stop-btn"),
        sessionBadge: document.getElementById("session-badge"),

        // User & Guest Account Elements
        registeredUserCard: document.getElementById("registered-user-card"),
        guestUserCard: document.getElementById("guest-user-card"),
        userAvatarText: document.getElementById("user-avatar-text"),
        userDisplayName: document.getElementById("user-display-name"),
        userDisplayEmail: document.getElementById("user-display-email"),
        guestUsageText: document.getElementById("guest-usage-text"),
        btnOpenUpgradeModal: document.getElementById("btn-open-upgrade-modal"),
        btnLogout: document.getElementById("btn-logout"),
        headerLogoutBtn: document.getElementById("header-logout-btn"),
        
        // Upgrade Modal
        upgradeModal: document.getElementById("upgrade-modal"),
        upgradeCancelBtn: document.getElementById("upgrade-cancel-btn"),
        formUpgradeGuest: document.getElementById("form-upgrade-guest"),

        // Modals & Dropdown
        renameModal: document.getElementById("rename-modal"),
        renameInput: document.getElementById("rename-input"),
        renameCancelBtn: document.getElementById("rename-cancel-btn"),
        renameConfirmBtn: document.getElementById("rename-confirm-btn"),
        
        deleteModal: document.getElementById("delete-modal"),
        deleteCancelBtn: document.getElementById("delete-cancel-btn"),
        deleteConfirmBtn: document.getElementById("delete-confirm-btn"),
        
        clearAllModal: document.getElementById("clear-all-modal"),
        clearAllCancelBtn: document.getElementById("clear-all-cancel-btn"),
        clearAllConfirmBtn: document.getElementById("clear-all-confirm-btn"),
        
        dropdownMenu: document.getElementById("history-dropdown-menu"),
        dropdownRenameBtn: document.getElementById("dropdown-rename-btn"),
        dropdownDeleteBtn: document.getElementById("dropdown-delete-btn"),
    };

    // ---------------------------------------------------------------------------
    // Utilities
    // ---------------------------------------------------------------------------
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

    function formatTime(isoString) {
        try {
            const date = isoString ? new Date(isoString) : new Date();
            return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
        } catch {
            return "";
        }
    }

    function getDateCategory(dateString) {
        if (!dateString) return "Older";
        const date = new Date(dateString);
        const now = new Date();
        
        const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
        const startOfYesterday = new Date(startOfToday);
        startOfYesterday.setDate(startOfYesterday.getDate() - 1);
        const startOf7Days = new Date(startOfToday);
        startOf7Days.setDate(startOf7Days.getDate() - 7);

        if (date >= startOfToday) {
            return "Today";
        } else if (date >= startOfYesterday) {
            return "Yesterday";
        } else if (date >= startOf7Days) {
            return "Previous 7 Days";
        } else {
            return "Older";
        }
    }

    // ---------------------------------------------------------------------------
    // Theme Management
    // ---------------------------------------------------------------------------
    function initTheme() {
        const savedTheme = localStorage.getItem("studybuddy_theme") || "dark";
        setTheme(savedTheme);
    }

    function setTheme(theme) {
        state.theme = theme;
        document.documentElement.setAttribute("data-theme", theme);
        localStorage.setItem("studybuddy_theme", theme);
        if (elements.themeLabel) {
            elements.themeLabel.textContent = theme === "dark" ? "Dark Mode" : "Light Mode";
        }
    }

    function toggleTheme() {
        setTheme(state.theme === "dark" ? "light" : "dark");
    }

    // ---------------------------------------------------------------------------
    // System Status & Notification Banner
    // ---------------------------------------------------------------------------
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

    function showNotification(message, type = "error") {
        if (!elements.notificationBanner || !elements.bannerText) return;
        elements.notificationBanner.classList.remove("hidden", "warning");
        if (type === "warning") {
            elements.notificationBanner.classList.add("warning");
        }
        elements.bannerText.textContent = message;
    }

    function hideNotification() {
        if (elements.notificationBanner) {
            elements.notificationBanner.classList.add("hidden");
        }
    }

    // ---------------------------------------------------------------------------
    // User Profile & Authentication Logic
    // ---------------------------------------------------------------------------
    async function loadCurrentUser() {
        try {
            const res = await fetch("/auth/me");
            if (res.ok) {
                const data = await res.json();
                state.currentUser = data.user;
                renderUserCard();
            }
        } catch (err) {
            console.error("Failed to load user profile:", err);
        }
    }

    function renderUserCard() {
        const user = state.currentUser;
        if (!user) return;

        if (user.is_guest) {
            if (elements.registeredUserCard) elements.registeredUserCard.classList.add("hidden");
            if (elements.guestUserCard) {
                elements.guestUserCard.classList.remove("hidden");
                if (elements.guestUsageText) {
                    elements.guestUsageText.textContent = `${user.guest_message_count || 0}/${user.guest_limit || 25} used`;
                }
            }
        } else {
            if (elements.guestUserCard) elements.guestUserCard.classList.add("hidden");
            if (elements.registeredUserCard) {
                elements.registeredUserCard.classList.remove("hidden");
                if (elements.userDisplayName) elements.userDisplayName.textContent = user.name || "Student";
                if (elements.userDisplayEmail) elements.userDisplayEmail.textContent = user.email || "";
                if (elements.userAvatarText) {
                    elements.userAvatarText.textContent = user.name ? user.name.slice(0, 2).toUpperCase() : "ST";
                }
            }
        }
    }

    async function handleLogout() {
        try {
            await fetch("/auth/logout", { method: "POST" });
            window.location.reload();
        } catch (err) {
            window.location.href = "/login";
        }
    }

    function openUpgradeModal() {
        if (elements.upgradeModal) {
            elements.upgradeModal.classList.remove("hidden");
            const nameInput = document.getElementById("upgrade-name");
            if (nameInput) nameInput.focus();
        }
    }

    function closeUpgradeModal() {
        if (elements.upgradeModal) {
            elements.upgradeModal.classList.add("hidden");
        }
    }

    async function handleUpgradeGuestSubmit(e) {
        e.preventDefault();
        const name = document.getElementById("upgrade-name").value.trim();
        const email = document.getElementById("upgrade-email").value.trim();
        const password = document.getElementById("upgrade-password").value;
        const transfer_chats = document.getElementById("upgrade-transfer-chats").checked;
        const submitBtn = document.getElementById("upgrade-confirm-btn");

        if (password.length < 6) {
            showNotification("Password must be at least 6 characters.");
            return;
        }

        submitBtn.disabled = true;
        submitBtn.textContent = "Upgrading...";

        try {
            const res = await fetch("/auth/upgrade-guest", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ name, email, password, transfer_chats })
            });
            const data = await res.json();
            if (res.ok) {
                state.currentUser = data.user;
                closeUpgradeModal();
                renderUserCard();
                showNotification(`Account upgraded successfully! Welcome, ${data.user.name || "Student"}!`, "warning");
                loadConversations(false);
            } else {
                showNotification(data.error || "Failed to upgrade account.");
            }
        } catch (err) {
            showNotification("Failed to communicate with server.");
        } finally {
            submitBtn.disabled = false;
            submitBtn.textContent = "Create & Transfer";
        }
    }

    // ---------------------------------------------------------------------------
    // Sidebar Conversations Management & Grouping
    // ---------------------------------------------------------------------------
    async function loadConversations(autoSelectRecent = false) {
        try {
            const res = await fetch("/conversations");
            if (!res.ok) throw new Error("Failed to load conversations");
            const data = await res.json();
            state.conversations = data.conversations || [];
            renderSidebarHistory();

            if (autoSelectRecent && state.conversations.length > 0) {
                selectConversation(state.conversations[0].id);
            } else if (!state.conversationId) {
                initNewChat();
            }
        } catch (err) {
            console.error("Error loading conversations:", err);
            renderSidebarHistory();
            if (!state.conversationId) initNewChat();
        }
    }

    function renderSidebarHistory() {
        if (!elements.historyList) return;
        elements.historyList.innerHTML = "";

        const query = state.searchQuery.toLowerCase().trim();
        const filtered = state.conversations.filter(c => {
            if (!query) return true;
            return (c.title && c.title.toLowerCase().includes(query)) ||
                   (c.last_message && c.last_message.toLowerCase().includes(query));
        });

        if (filtered.length === 0) {
            if (elements.historyEmptyState) elements.historyEmptyState.classList.remove("hidden");
            return;
        } else {
            if (elements.historyEmptyState) elements.historyEmptyState.classList.add("hidden");
        }

        const groups = {
            "Today": [],
            "Yesterday": [],
            "Previous 7 Days": [],
            "Older": [],
        };

        filtered.forEach(c => {
            const cat = getDateCategory(c.updated_at || c.created_at);
            if (groups[cat]) {
                groups[cat].push(c);
            } else {
                groups["Older"].push(c);
            }
        });

        ["Today", "Yesterday", "Previous 7 Days", "Older"].forEach(groupName => {
            const list = groups[groupName];
            if (list.length === 0) return;

            const header = document.createElement("div");
            header.className = "history-group-header";
            header.textContent = groupName;
            elements.historyList.appendChild(header);

            list.forEach(c => {
                const item = document.createElement("div");
                item.className = `history-item ${c.id === state.conversationId ? "active" : ""}`;
                item.setAttribute("data-id", c.id);
                item.setAttribute("title", c.title);

                const icon = document.createElement("div");
                icon.className = "history-item-icon";
                icon.innerHTML = `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path></svg>`;

                const titleSpan = document.createElement("span");
                titleSpan.className = "history-item-title";
                titleSpan.textContent = c.title || "Untitled Session";

                const actions = document.createElement("div");
                actions.className = "history-item-actions";
                
                const menuBtn = document.createElement("button");
                menuBtn.type = "button";
                menuBtn.className = "history-menu-trigger";
                menuBtn.setAttribute("aria-label", "Conversation options");
                menuBtn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="1"></circle><circle cx="19" cy="12" r="1"></circle><circle cx="5" cy="12" r="1"></circle></svg>`;

                menuBtn.addEventListener("click", function (e) {
                    e.stopPropagation();
                    openDropdownMenu(c.id, menuBtn);
                });

                actions.appendChild(menuBtn);
                item.appendChild(icon);
                item.appendChild(titleSpan);
                item.appendChild(actions);

                item.addEventListener("click", function () {
                    selectConversation(c.id);
                });

                elements.historyList.appendChild(item);
            });
        });
    }

    // ---------------------------------------------------------------------------
    // Three-dot Dropdown Menu Handling
    // ---------------------------------------------------------------------------
    function openDropdownMenu(convId, anchorElem) {
        state.dropdownTargetId = convId;
        const rect = anchorElem.getBoundingClientRect();
        
        elements.dropdownMenu.style.top = `${rect.bottom + 4}px`;
        elements.dropdownMenu.style.left = `${Math.min(rect.left, window.innerWidth - 150)}px`;
        elements.dropdownMenu.classList.remove("hidden");
    }

    function closeDropdownMenu() {
        if (elements.dropdownMenu) {
            elements.dropdownMenu.classList.add("hidden");
        }
        state.dropdownTargetId = null;
    }

    // ---------------------------------------------------------------------------
    // Select & Open Conversation
    // ---------------------------------------------------------------------------
    async function selectConversation(convId) {
        if (state.isGenerating) return;
        closeMobileSidebar();
        closeDropdownMenu();

        try {
            const res = await fetch(`/conversations/${convId}`);
            if (!res.ok) {
                showNotification("Could not load selected conversation.");
                return;
            }
            const data = await res.json();
            const conv = data.conversation;
            const msgs = data.messages || [];

            state.conversationId = conv.id;
            state.conversationTitle = conv.title || "Study Session";
            state.messages = msgs;

            if (elements.titleText) elements.titleText.textContent = state.conversationTitle;
            if (elements.sessionBadge) {
                elements.sessionBadge.textContent = `ID: ${state.conversationId.slice(0, 8)}...`;
                elements.sessionBadge.title = `Full ID: ${state.conversationId}`;
            }

            renderMessagesList(msgs);
            renderSidebarHistory();
            hideNotification();
            setStatus("ready");

            if (elements.userInput) {
                elements.userInput.focus();
            }
        } catch (err) {
            console.error("Failed to select conversation:", err);
            showNotification("Failed to connect to database.");
        }
    }

    // ---------------------------------------------------------------------------
    // New Chat Action
    // ---------------------------------------------------------------------------
    function initNewChat() {
        if (state.isGenerating) return;
        state.conversationId = generateUUID();
        state.conversationTitle = "New Study Session";
        state.messages = [];

        if (elements.titleText) elements.titleText.textContent = state.conversationTitle;
        if (elements.sessionBadge) {
            elements.sessionBadge.textContent = `ID: ${state.conversationId.slice(0, 8)}...`;
            elements.sessionBadge.title = `Full ID: ${state.conversationId}`;
        }

        if (elements.messagesList) elements.messagesList.innerHTML = "";
        if (elements.welcomeScreen) elements.welcomeScreen.classList.remove("hidden");

        renderSidebarHistory();
        hideNotification();
        setStatus("ready");
        closeMobileSidebar();

        if (elements.userInput) {
            elements.userInput.value = "";
            elements.userInput.style.height = "auto";
            elements.userInput.focus();
        }
    }

    // ---------------------------------------------------------------------------
    // Modals: Rename & Delete
    // ---------------------------------------------------------------------------
    function openRenameModal(convId) {
        closeDropdownMenu();
        const conv = state.conversations.find(c => c.id === convId);
        state.renameTargetId = convId;
        if (elements.renameInput) {
            elements.renameInput.value = conv ? conv.title : "";
            elements.renameModal.classList.remove("hidden");
            elements.renameInput.focus();
            elements.renameInput.select();
        }
    }

    function closeRenameModal() {
        if (elements.renameModal) elements.renameModal.classList.add("hidden");
        state.renameTargetId = null;
    }

    async function handleRenameConfirm() {
        const convId = state.renameTargetId;
        const newTitle = elements.renameInput.value.trim();
        if (!convId || !newTitle) return;

        try {
            const res = await fetch(`/conversations/${convId}`, {
                method: "PATCH",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ title: newTitle }),
            });

            if (!res.ok) throw new Error("Rename failed");

            const target = state.conversations.find(c => c.id === convId);
            if (target) target.title = newTitle;

            if (state.conversationId === convId) {
                state.conversationTitle = newTitle;
                if (elements.titleText) elements.titleText.textContent = newTitle;
            }

            renderSidebarHistory();
            closeRenameModal();
        } catch (err) {
            console.error("Rename error:", err);
            showNotification("Failed to rename conversation.");
        }
    }

    function openDeleteModal(convId) {
        closeDropdownMenu();
        state.deleteTargetId = convId;
        if (elements.deleteModal) {
            elements.deleteModal.classList.remove("hidden");
        }
    }

    function closeDeleteModal() {
        if (elements.deleteModal) elements.deleteModal.classList.add("hidden");
        state.deleteTargetId = null;
    }

    async function handleDeleteConfirm() {
        const convId = state.deleteTargetId;
        if (!convId) return;

        try {
            const res = await fetch(`/conversations/${convId}`, {
                method: "DELETE",
            });
            if (!res.ok) throw new Error("Delete failed");

            state.conversations = state.conversations.filter(c => c.id !== convId);
            closeDeleteModal();

            if (state.conversationId === convId) {
                if (state.conversations.length > 0) {
                    selectConversation(state.conversations[0].id);
                } else {
                    initNewChat();
                }
            } else {
                renderSidebarHistory();
            }
        } catch (err) {
            console.error("Delete error:", err);
            showNotification("Failed to delete conversation.");
        }
    }

    function openClearAllModal() {
        if (elements.clearAllModal) {
            elements.clearAllModal.classList.remove("hidden");
        }
    }

    function closeClearAllModal() {
        if (elements.clearAllModal) {
            elements.clearAllModal.classList.add("hidden");
        }
    }

    async function handleClearAllConfirm() {
        try {
            for (const c of state.conversations) {
                await fetch(`/conversations/${c.id}`, { method: "DELETE" });
            }
            state.conversations = [];
            closeClearAllModal();
            initNewChat();
        } catch (err) {
            console.error("Clear all error:", err);
            showNotification("Failed to clear all conversations.");
        }
    }

    // ---------------------------------------------------------------------------
    // Markdown Rendering & Syntax Highlighting (XSS-Safe)
    // ---------------------------------------------------------------------------
    function tokenizeCode(codeText, lang) {
        const keywords = new Set([
            "def", "return", "import", "from", "class", "if", "elif", "else", "for",
            "while", "try", "except", "finally", "with", "as", "pass", "break", "continue",
            "and", "or", "not", "is", "in", "lambda", "yield", "async", "await", "self",
            "function", "const", "let", "var", "new", "typeof", "instanceof", "switch", "case",
            "SELECT", "FROM", "WHERE", "INSERT", "UPDATE", "DELETE", "JOIN", "TABLE"
        ]);

        const fragment = document.createDocumentFragment();
        const regex = /(#[^\n]*|\/\/[^\n]*|"""[\s\S]*?"""|'''[\s\S]*?'''|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|\b\d+(?:\.\d+)?\b|\b[a-zA-Z_][a-zA-Z0-9_]*\b|[+\-*/%=<>!&|^~]+)/g;

        let lastIndex = 0;
        let match;

        while ((match = regex.exec(codeText)) !== null) {
            if (match.index > lastIndex) {
                fragment.appendChild(document.createTextNode(codeText.slice(lastIndex, match.index)));
            }

            const token = match[0];
            const span = document.createElement("span");

            if (token.startsWith("#") || token.startsWith("//") || token.startsWith('"""') || token.startsWith("'''")) {
                span.className = "tok-com";
                span.textContent = token;
            } else if (token.startsWith('"') || token.startsWith("'")) {
                span.className = "tok-str";
                span.textContent = token;
            } else if (/^\d/.test(token)) {
                span.className = "tok-num";
                span.textContent = token;
            } else if (keywords.has(token)) {
                span.className = "tok-kw";
                span.textContent = token;
            } else if (/^[+\-*/%=<>!&|^~]+$/.test(token)) {
                span.className = "tok-op";
                span.textContent = token;
            } else {
                span.textContent = token;
            }

            fragment.appendChild(span);
            lastIndex = match.index + token.length;
        }

        if (lastIndex < codeText.length) {
            fragment.appendChild(document.createTextNode(codeText.slice(lastIndex)));
        }

        return fragment;
    }

    function renderSafeMessageContent(container, rawText) {
        const codeBlockRegex = /```([a-zA-Z0-9_\-#+]*)\n([\s\S]*?)```/g;
        let lastIndex = 0;
        let match;

        while ((match = codeBlockRegex.exec(rawText)) !== null) {
            const textBefore = rawText.slice(lastIndex, match.index);
            if (textBefore) {
                renderTextParagraphs(container, textBefore);
            }

            const lang = (match[1] || "code").toLowerCase();
            const codeContent = match[2];

            const codeBox = document.createElement("div");
            codeBox.className = "code-container";

            const codeHeader = document.createElement("div");
            codeHeader.className = "code-header";

            const langLabel = document.createElement("span");
            langLabel.className = "code-lang-label";
            langLabel.textContent = lang.toUpperCase();

            const copyBtn = document.createElement("button");
            copyBtn.type = "button";
            copyBtn.className = "code-copy-btn";
            copyBtn.innerHTML = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg><span>Copy Code</span>`;

            copyBtn.addEventListener("click", function () {
                navigator.clipboard.writeText(codeContent).then(() => {
                    copyBtn.innerHTML = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#10b981" stroke-width="2.5"><polyline points="20 6 9 17 4 12"></polyline></svg><span style="color:#10b981">Copied!</span>`;
                    setTimeout(() => {
                        copyBtn.innerHTML = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg><span>Copy Code</span>`;
                    }, 2000);
                }).catch(() => {
                    copyBtn.textContent = "Failed";
                });
            });

            codeHeader.appendChild(langLabel);
            codeHeader.appendChild(copyBtn);
            codeBox.appendChild(codeHeader);

            const pre = document.createElement("pre");
            const code = document.createElement("code");
            code.appendChild(tokenizeCode(codeContent, lang));
            pre.appendChild(code);
            codeBox.appendChild(pre);

            container.appendChild(codeBox);
            lastIndex = match.index + match[0].length;
        }

        const remainingText = rawText.slice(lastIndex);
        if (remainingText) {
            renderTextParagraphs(container, remainingText);
        }
    }

    function renderInlineFormattedText(parent, text) {
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

    function renderTextParagraphs(container, text) {
        const blocks = text.split(/\n\s*\n/);
        for (const block of blocks) {
            const clean = block.trim();
            if (!clean) continue;

            if (clean.startsWith("### ")) {
                const h3 = document.createElement("h3");
                renderInlineFormattedText(h3, clean.slice(4));
                container.appendChild(h3);
                continue;
            } else if (clean.startsWith("## ")) {
                const h2 = document.createElement("h2");
                renderInlineFormattedText(h2, clean.slice(3));
                container.appendChild(h2);
                continue;
            } else if (clean.startsWith("# ")) {
                const h1 = document.createElement("h1");
                renderInlineFormattedText(h1, clean.slice(2));
                container.appendChild(h1);
                continue;
            }

            if (clean.startsWith("> ")) {
                const bq = document.createElement("blockquote");
                renderInlineFormattedText(bq, clean.slice(2));
                container.appendChild(bq);
                continue;
            }

            const lines = clean.split("\n");

            if (lines.every(line => /^[-*]\s+/.test(line.trim()))) {
                const ul = document.createElement("ul");
                for (const line of lines) {
                    const li = document.createElement("li");
                    renderInlineFormattedText(li, line.trim().replace(/^[-*]\s+/, ""));
                    ul.appendChild(li);
                }
                container.appendChild(ul);
                continue;
            }

            if (lines.every(line => /^\d+\.\s+/.test(line.trim()))) {
                const ol = document.createElement("ol");
                for (const line of lines) {
                    const li = document.createElement("li");
                    renderInlineFormattedText(li, line.trim().replace(/^\d+\.\s+/, ""));
                    ol.appendChild(li);
                }
                container.appendChild(ol);
                continue;
            }

            const p = document.createElement("p");
            renderInlineFormattedText(p, clean);
            container.appendChild(p);
        }
    }

    // ---------------------------------------------------------------------------
    // Messages Rendering & Action Toolbar
    // ---------------------------------------------------------------------------
    function renderMessagesList(messages) {
        if (!elements.messagesList) return;
        elements.messagesList.innerHTML = "";

        if (!messages || messages.length === 0) {
            if (elements.welcomeScreen) elements.welcomeScreen.classList.remove("hidden");
            return;
        }

        if (elements.welcomeScreen) elements.welcomeScreen.classList.add("hidden");

        messages.forEach((msg, idx) => {
            const isLast = idx === messages.length - 1;
            appendMessage(msg.role, msg.content, msg.timestamp, isLast);
        });

        scrollToBottom();
    }

    function appendMessage(role, text, timestamp, isLastTurn = true) {
        if (elements.welcomeScreen) {
            elements.welcomeScreen.classList.add("hidden");
        }

        const isUser = role === "user";
        const messageItem = document.createElement("div");
        messageItem.className = `message-item ${isUser ? "user" : "ai"}`;

        const avatar = document.createElement("div");
        avatar.className = `avatar ${isUser ? "user-avatar" : "ai-avatar"}`;
        avatar.innerHTML = isUser
            ? `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle></svg>`
            : `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2a10 10 0 0 1 10 10c0 5.523-4.477 10-10 10a9.957 9.957 0 0 1-4.73-1.189L2 22l1.248-5.068A9.96 9.96 0 0 1 2 12C2 6.477 6.477 2 12 2z"></path><path d="m9 12 2 2 4-4"></path></svg>`;

        const contentWrapper = document.createElement("div");
        contentWrapper.className = "message-content";

        const bubble = document.createElement("div");
        bubble.className = "message-bubble";
        renderSafeMessageContent(bubble, text);

        const meta = document.createElement("div");
        meta.className = "message-meta";
        meta.textContent = `${isUser ? "You" : "StudyBuddy AI"} • ${formatTime(timestamp)}`;

        contentWrapper.appendChild(bubble);
        contentWrapper.appendChild(meta);

        if (!isUser) {
            const actionsBar = document.createElement("div");
            actionsBar.className = "message-actions-bar";

            const copyResponseBtn = document.createElement("button");
            copyResponseBtn.type = "button";
            copyResponseBtn.className = "btn-msg-action";
            copyResponseBtn.innerHTML = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg><span>Copy</span>`;

            copyResponseBtn.addEventListener("click", function () {
                navigator.clipboard.writeText(text).then(() => {
                    copyResponseBtn.innerHTML = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#10b981" stroke-width="2.5"><polyline points="20 6 9 17 4 12"></polyline></svg><span style="color:#10b981">Copied!</span>`;
                    setTimeout(() => {
                        copyResponseBtn.innerHTML = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg><span>Copy</span>`;
                    }, 2000);
                });
            });
            actionsBar.appendChild(copyResponseBtn);

            if (isLastTurn) {
                const regenBtn = document.createElement("button");
                regenBtn.type = "button";
                regenBtn.className = "btn-msg-action regen-btn";
                regenBtn.innerHTML = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="1 4 1 10 7 10"></polyline><polyline points="23 20 23 14 17 14"></polyline><path d="M20.49 9A9 9 0 0 0 5.64 5.64L1 10m22 4l-4.64 4.36A9 9 0 0 1 3.51 15"></path></svg><span>Regenerate</span>`;

                regenBtn.addEventListener("click", function () {
                    regenerateLastResponse();
                });
                actionsBar.appendChild(regenBtn);
            }

            contentWrapper.appendChild(actionsBar);
        }

        messageItem.appendChild(avatar);
        messageItem.appendChild(contentWrapper);

        elements.messagesList.appendChild(messageItem);
        scrollToBottom();
    }

    function scrollToBottom() {
        if (!elements.messagesArea) return;
        requestAnimationFrame(() => {
            elements.messagesArea.scrollTop = elements.messagesArea.scrollHeight;
        });
    }

    // ---------------------------------------------------------------------------
    // Message Dispatch, Regeneration & Stop Control
    // ---------------------------------------------------------------------------
    function setGeneratingState(isGenerating) {
        state.isGenerating = isGenerating;
        if (elements.sendBtn) elements.sendBtn.disabled = isGenerating;
        if (elements.userInput) elements.userInput.disabled = isGenerating;

        if (elements.stopBtn) {
            if (isGenerating) {
                elements.stopBtn.classList.remove("hidden");
            } else {
                elements.stopBtn.classList.add("hidden");
            }
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

    async function sendMessage(promptOverride) {
        const text = (promptOverride || elements.userInput.value || "").trim();
        if (!text || state.isGenerating) return;

        hideNotification();

        // 1. Render User message in UI
        const nowIso = new Date().toISOString();
        appendMessage("user", text, nowIso);
        state.messages.push({ role: "user", content: text, timestamp: nowIso });

        elements.userInput.value = "";
        elements.userInput.style.height = "auto";

        state.activeAbortController = new AbortController();
        setGeneratingState(true);

        try {
            const res = await fetch("/chat", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    message: text,
                    conversation_id: state.conversationId,
                }),
                signal: state.activeAbortController.signal,
            });

            const data = await res.json().catch(() => ({}));

            if (!res.ok) {
                const errorMsg = data.error || `Server responded with HTTP ${res.status}`;
                setStatus("error");

                if (res.status === 403 && data.limit_reached) {
                    showNotification(errorMsg, "warning");
                    openUpgradeModal();
                } else {
                    showNotification(errorMsg, res.status === 503 ? "warning" : "error");
                }

                const errCard = document.createElement("div");
                errCard.className = "message-item ai";
                errCard.innerHTML = `
                    <div class="avatar ai-avatar" style="background:#ef4444">!</div>
                    <div class="message-content">
                        <div class="message-bubble" style="border-left: 3px solid #ef4444">
                            <strong style="color:#ef4444">Unable to generate response</strong>
                            <p style="margin-top:4px">${errorMsg}</p>
                        </div>
                    </div>
                `;
                elements.messagesList.appendChild(errCard);
                scrollToBottom();
                return;
            }

            if (data.conversation_id) state.conversationId = data.conversation_id;
            if (data.title) {
                state.conversationTitle = data.title;
                if (elements.titleText) elements.titleText.textContent = data.title;
            }

            // Update guest usage count if applicable
            if (data.is_guest && typeof data.guest_message_count === "number" && state.currentUser) {
                state.currentUser.guest_message_count = data.guest_message_count;
                renderUserCard();
            }

            const replyText = data.reply || "";
            const replyIso = new Date().toISOString();
            state.messages.push({ role: "model", content: replyText, timestamp: replyIso });
            appendMessage("model", replyText, replyIso, true);

            loadConversations(false);

        } catch (err) {
            if (err.name === "AbortError") {
                showNotification("Generation stopped by user.", "warning");
            } else {
                console.error("Communication failure:", err);
                setStatus("error");
                showNotification("Failed to communicate with StudyBuddy AI backend.", "error");
            }
        } finally {
            state.activeAbortController = null;
            setGeneratingState(false);
            if (elements.userInput) elements.userInput.focus();
        }
    }

    async function regenerateLastResponse() {
        if (state.isGenerating || !state.conversationId) return;

        const aiItems = elements.messagesList.querySelectorAll(".message-item.ai");
        if (aiItems.length > 0) {
            aiItems[aiItems.length - 1].remove();
        }

        state.activeAbortController = new AbortController();
        setGeneratingState(true);

        try {
            const res = await fetch("/chat", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    conversation_id: state.conversationId,
                    regenerate: true,
                }),
                signal: state.activeAbortController.signal,
            });

            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                showNotification(data.error || "Regeneration failed.");
                return;
            }

            const newReply = data.reply || "";
            const replyIso = new Date().toISOString();
            appendMessage("model", newReply, replyIso, true);
            loadConversations(false);

        } catch (err) {
            if (err.name === "AbortError") {
                showNotification("Regeneration stopped.", "warning");
            } else {
                showNotification("Regeneration request failed.");
            }
        } finally {
            state.activeAbortController = null;
            setGeneratingState(false);
        }
    }

    function stopGeneration() {
        if (state.activeAbortController) {
            state.activeAbortController.abort();
            state.activeAbortController = null;
        }
    }

    // ---------------------------------------------------------------------------
    // Sidebar Collapse & Mobile Drawer
    // ---------------------------------------------------------------------------
    function toggleSidebarCollapse() {
        elements.appLayout.classList.toggle("sidebar-collapsed");
        const isCollapsed = elements.appLayout.classList.contains("sidebar-collapsed");
        if (elements.desktopExpandBtn) {
            if (isCollapsed) {
                elements.desktopExpandBtn.classList.remove("hidden");
            } else {
                elements.desktopExpandBtn.classList.add("hidden");
            }
        }
    }

    function openMobileSidebar() {
        elements.appLayout.classList.add("sidebar-mobile-open");
    }

    function closeMobileSidebar() {
        elements.appLayout.classList.remove("sidebar-mobile-open");
    }

    // ---------------------------------------------------------------------------
    // Auto-Resize Textarea
    // ---------------------------------------------------------------------------
    function autoResizeTextarea() {
        if (!elements.userInput) return;
        elements.userInput.style.height = "auto";
        const newHeight = Math.min(elements.userInput.scrollHeight, 180);
        elements.userInput.style.height = `${Math.max(newHeight, 32)}px`;
    }

    // ---------------------------------------------------------------------------
    // Event Registration
    // ---------------------------------------------------------------------------
    function registerEvents() {
        if (elements.chatForm) {
            elements.chatForm.addEventListener("submit", function (e) {
                e.preventDefault();
                sendMessage();
            });
        }

        if (elements.stopBtn) {
            elements.stopBtn.addEventListener("click", stopGeneration);
        }

        if (elements.userInput) {
            elements.userInput.addEventListener("keydown", function (e) {
                if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    sendMessage();
                }
            });
            elements.userInput.addEventListener("input", autoResizeTextarea);
        }

        if (elements.sidebarNewChatBtn) {
            elements.sidebarNewChatBtn.addEventListener("click", initNewChat);
        }
        if (elements.headerNewChatBtn) {
            elements.headerNewChatBtn.addEventListener("click", initNewChat);
        }

        if (elements.suggestionCards) {
            elements.suggestionCards.forEach(card => {
                card.addEventListener("click", function () {
                    const prompt = this.getAttribute("data-prompt");
                    if (prompt && !state.isGenerating) {
                        elements.userInput.value = prompt;
                        autoResizeTextarea();
                        sendMessage(prompt);
                    }
                });
            });
        }

        if (elements.sidebarCollapseBtn) {
            elements.sidebarCollapseBtn.addEventListener("click", toggleSidebarCollapse);
        }
        if (elements.desktopExpandBtn) {
            elements.desktopExpandBtn.addEventListener("click", toggleSidebarCollapse);
        }

        if (elements.mobileMenuBtn) {
            elements.mobileMenuBtn.addEventListener("click", openMobileSidebar);
        }
        if (elements.sidebarBackdrop) {
            elements.sidebarBackdrop.addEventListener("click", closeMobileSidebar);
        }

        // Search Input & Clear
        if (elements.historySearchInput) {
            elements.historySearchInput.addEventListener("input", function () {
                state.searchQuery = this.value;
                if (elements.searchClearBtn) {
                    if (this.value) {
                        elements.searchClearBtn.classList.remove("hidden");
                    } else {
                        elements.searchClearBtn.classList.add("hidden");
                    }
                }
                renderSidebarHistory();
            });
        }
        if (elements.searchClearBtn) {
            elements.searchClearBtn.addEventListener("click", function () {
                elements.historySearchInput.value = "";
                state.searchQuery = "";
                elements.searchClearBtn.classList.add("hidden");
                renderSidebarHistory();
            });
        }

        // Dropdown Menu actions
        if (elements.dropdownRenameBtn) {
            elements.dropdownRenameBtn.addEventListener("click", function () {
                if (state.dropdownTargetId) {
                    openRenameModal(state.dropdownTargetId);
                }
            });
        }
        if (elements.dropdownDeleteBtn) {
            elements.dropdownDeleteBtn.addEventListener("click", function () {
                if (state.dropdownTargetId) {
                    openDeleteModal(state.dropdownTargetId);
                }
            });
        }

        document.addEventListener("click", function (e) {
            if (elements.dropdownMenu && !elements.dropdownMenu.contains(e.target)) {
                closeDropdownMenu();
            }
        });

        // Rename Modal Buttons
        if (elements.renameCancelBtn) {
            elements.renameCancelBtn.addEventListener("click", closeRenameModal);
        }
        if (elements.renameConfirmBtn) {
            elements.renameConfirmBtn.addEventListener("click", handleRenameConfirm);
        }
        if (elements.renameInput) {
            elements.renameInput.addEventListener("keydown", function (e) {
                if (e.key === "Enter") handleRenameConfirm();
                if (e.key === "Escape") closeRenameModal();
            });
        }

        // Delete Modal Buttons
        if (elements.deleteCancelBtn) {
            elements.deleteCancelBtn.addEventListener("click", closeDeleteModal);
        }
        if (elements.deleteConfirmBtn) {
            elements.deleteConfirmBtn.addEventListener("click", handleDeleteConfirm);
        }

        // Clear All History Buttons
        if (elements.clearAllBtn) {
            elements.clearAllBtn.addEventListener("click", openClearAllModal);
        }
        if (elements.clearAllCancelBtn) {
            elements.clearAllCancelBtn.addEventListener("click", closeClearAllModal);
        }
        if (elements.clearAllConfirmBtn) {
            elements.clearAllConfirmBtn.addEventListener("click", handleClearAllConfirm);
        }

        // Upgrade Guest Modal Buttons
        if (elements.btnOpenUpgradeModal) {
            elements.btnOpenUpgradeModal.addEventListener("click", openUpgradeModal);
        }
        if (elements.upgradeCancelBtn) {
            elements.upgradeCancelBtn.addEventListener("click", closeUpgradeModal);
        }
        if (elements.formUpgradeGuest) {
            elements.formUpgradeGuest.addEventListener("submit", handleUpgradeGuestSubmit);
        }

        // Logout Buttons
        if (elements.btnLogout) {
            elements.btnLogout.addEventListener("click", handleLogout);
        }
        if (elements.headerLogoutBtn) {
            elements.headerLogoutBtn.addEventListener("click", handleLogout);
        }

        // Theme Toggle Button
        if (elements.themeToggleBtn) {
            elements.themeToggleBtn.addEventListener("click", toggleTheme);
        }

        // Notification Banner Dismiss
        if (elements.bannerCloseBtn) {
            elements.bannerCloseBtn.addEventListener("click", hideNotification);
        }

        // Click Active Title in Header to Rename
        if (elements.activeConvTitle) {
            elements.activeConvTitle.addEventListener("click", function () {
                if (state.conversationId) {
                    openRenameModal(state.conversationId);
                }
            });
        }

        // Global Keyboard Shortcuts
        document.addEventListener("keydown", function (e) {
            if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "n") {
                e.preventDefault();
                initNewChat();
            }
            if ((e.metaKey || e.ctrlKey) && e.key === "[") {
                e.preventDefault();
                toggleSidebarCollapse();
            }
            if (e.key === "Escape") {
                closeRenameModal();
                closeDeleteModal();
                closeClearAllModal();
                closeUpgradeModal();
                closeDropdownMenu();
                closeMobileSidebar();
            }
        });
    }

    // ---------------------------------------------------------------------------
    // Initialization
    // ---------------------------------------------------------------------------
    document.addEventListener("DOMContentLoaded", function () {
        initTheme();
        registerEvents();
        loadCurrentUser();
        loadConversations(true);
    });
})();

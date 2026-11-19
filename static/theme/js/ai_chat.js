/* EuphoriaDJ local AI shopping assistant */
(function () {
    'use strict';

    var root = document.querySelector('[data-ai-chat]');
    if (!root) {
        return;
    }

    var toggle = root.querySelector('[data-ai-toggle]');
    var panel = root.querySelector('[data-ai-panel]');
    var closeButton = root.querySelector('[data-ai-close]');
    var messages = root.querySelector('[data-ai-messages]');
    var suggestions = root.querySelector('[data-ai-suggestions]');
    var form = root.querySelector('[data-ai-form]');
    var input = root.querySelector('[data-ai-input]');
    var sendButton = root.querySelector('[data-ai-send]');
    var statusText = root.querySelector('[data-ai-status-text]');
    var csrfInput = form ? form.querySelector('input[name="csrfmiddlewaretoken"]') : null;

    if (!toggle || !panel || !form || !input || !messages) {
        return;
    }

    var chatUrl = root.getAttribute('data-chat-url') || '/assistant/chat/';
    var signinUrl = root.getAttribute('data-signin-url') || '/login';
    var isLoading = false;
    var lastFocused = null;

    function csrfToken() {
        if (csrfInput && csrfInput.value) {
            return csrfInput.value;
        }
        var match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
        return match ? decodeURIComponent(match[1]) : '';
    }

    function scrollMessages() {
        // Set immediately so the latest reply is visible even in a background
        // tab where requestAnimationFrame callbacks may be paused, then repeat
        // after layout/images settle.
        messages.scrollTop = messages.scrollHeight;
        window.requestAnimationFrame(function () {
            messages.scrollTop = messages.scrollHeight;
        });
    }

    function setStatus(available) {
        if (!statusText) {
            return;
        }
        if (available) {
            root.classList.remove('is-offline');
            statusText.textContent = 'Local AI · catalog-grounded';
        } else {
            root.classList.add('is-offline');
            statusText.textContent = 'Catalog fallback mode';
        }
    }

    if (root.getAttribute('data-ai-enabled') !== 'true') {
        setStatus(false);
    }

    function openChat(prefill) {
        lastFocused = document.activeElement;
        panel.hidden = false;
        panel.classList.add('is-open');
        toggle.setAttribute('aria-expanded', 'true');
        if (typeof prefill === 'string' && prefill.trim()) {
            input.value = prefill.trim();
            resizeInput();
        }
        window.requestAnimationFrame(function () {
            input.focus();
            scrollMessages();
        });
    }

    function closeChat() {
        panel.hidden = true;
        panel.classList.remove('is-open');
        toggle.setAttribute('aria-expanded', 'false');
        if (lastFocused && typeof lastFocused.focus === 'function') {
            lastFocused.focus();
        }
    }

    function resizeInput() {
        input.style.height = 'auto';
        input.style.height = Math.min(input.scrollHeight, 104) + 'px';
    }

    function setLoading(loading) {
        isLoading = loading;
        if (sendButton) {
            sendButton.disabled = loading;
        }
        form.setAttribute('aria-busy', loading ? 'true' : 'false');
    }

    function appendMessage(role, text) {
        var row = document.createElement('div');
        row.className = 'ai-chat-message ai-chat-message-' + role;

        var content = document.createElement('div');
        content.className = 'ai-chat-message-content';

        var bubble = document.createElement('div');
        bubble.className = 'ai-chat-bubble';
        bubble.textContent = text || '';

        content.appendChild(bubble);
        row.appendChild(content);
        messages.appendChild(row);
        scrollMessages();
        return content;
    }

    function appendNotice(content, text) {
        if (!text) {
            return;
        }
        var notice = document.createElement('div');
        notice.className = 'ai-chat-notice';
        notice.textContent = text;
        var bubble = content.querySelector('.ai-chat-bubble');
        if (bubble) {
            content.insertBefore(notice, bubble);
        } else {
            content.appendChild(notice);
        }
    }

    function appendTyping() {
        var content = appendMessage('assistant', '');
        var bubble = content.querySelector('.ai-chat-bubble');
        bubble.textContent = '';
        bubble.setAttribute('aria-label', 'Assistant is typing');
        var typing = document.createElement('span');
        typing.className = 'ai-chat-typing';
        for (var i = 0; i < 3; i += 1) {
            typing.appendChild(document.createElement('span'));
        }
        bubble.appendChild(typing);
        // Return the whole row so removing the indicator leaves no empty gap.
        return content.closest('.ai-chat-message');
    }

    function renderLinks(content, links) {
        if (!Array.isArray(links) || !links.length) {
            return;
        }
        var wrap = document.createElement('div');
        wrap.className = 'ai-chat-links';
        links.forEach(function (item) {
            if (!item || !item.url || !item.label) {
                return;
            }
            var link = document.createElement('a');
            link.className = 'ai-chat-link';
            link.href = item.url;
            if (item.icon) {
                var icon = document.createElement('i');
                icon.className = item.icon;
                icon.setAttribute('aria-hidden', 'true');
                link.appendChild(icon);
            }
            link.appendChild(document.createTextNode(item.label));
            wrap.appendChild(link);
        });
        if (wrap.children.length) {
            content.appendChild(wrap);
        }
    }

    function productAddStatus(card, text, url) {
        var existing = card.querySelector('.ai-chat-product-status');
        if (existing) {
            existing.remove();
        }
        var status = document.createElement('p');
        status.className = 'ai-chat-product-status';
        status.textContent = text || '';
        if (url) {
            var link = document.createElement('a');
            link.href = url;
            link.textContent = ' Sign in';
            status.appendChild(link);
        }
        card.querySelector('.ai-chat-product-body').appendChild(status);
    }

    function updateProductCartLabel(card, quantity) {
        var label = card.querySelector('.ai-chat-in-cart');
        if (!quantity) {
            if (label) {
                label.remove();
            }
            return;
        }
        if (!label) {
            label = document.createElement('span');
            label.className = 'ai-chat-product-meta ai-chat-in-cart';
            card.querySelector('.ai-chat-product-actions').appendChild(label);
        }
        label.textContent = 'In cart ×' + quantity;
    }

    function updateCartCounts(count) {
        if (typeof count !== 'number') {
            return;
        }
        document.querySelectorAll('[data-cart-count-badge], [data-cart-count-label]').forEach(function (node) {
            node.textContent = String(count);
        });
        document.querySelectorAll('[data-cart-count-top-label]').forEach(function (node) {
            node.textContent = count + ' in cart';
        });
    }

    function addProduct(card, button, product) {
        var addUrl = product.add_url;
        if (!addUrl || button.disabled) {
            return;
        }
        var original = button.textContent;
        button.disabled = true;
        button.textContent = 'Adding…';

        fetch(addUrl, {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken()
            },
            body: JSON.stringify({ quantity: 1 })
        }).then(function (response) {
            return response.json().catch(function () {
                return {};
            }).then(function (data) {
                return { response: response, data: data };
            });
        }).then(function (result) {
            var response = result.response;
            var data = result.data;
            if (!response.ok) {
                if (response.status === 401) {
                    button.remove();
                    productAddStatus(card, data.message || 'Sign in to add products.', data.signin_url || signinUrl);
                    return;
                }
                throw new Error(data.error || 'Could not add this product.');
            }
            updateCartCounts(data.cart_count);
            updateProductCartLabel(card, data.product && data.product.in_cart_quantity);
            if (data.capped) {
                button.textContent = 'Max in cart';
                button.disabled = true;
            } else {
                button.textContent = 'Added';
                window.setTimeout(function () {
                    button.textContent = 'Add one more';
                    button.disabled = false;
                }, 1400);
            }
            productAddStatus(card, data.message || 'Added to your cart.');
        }).catch(function (error) {
            button.disabled = false;
            button.textContent = original;
            productAddStatus(card, error.message || 'Could not add this product.');
        });
    }

    function renderProductCard(content, product) {
        var card = document.createElement('article');
        card.className = 'ai-chat-product';

        var image = document.createElement('img');
        image.className = 'ai-chat-product-image';
        image.src = product.image_url || '';
        image.alt = product.name || 'Product';
        image.loading = 'lazy';
        image.addEventListener('error', function () {
            image.src = '/static/theme/img/product-1.png';
        }, { once: true });
        image.addEventListener('load', scrollMessages, { once: true });
        card.appendChild(image);

        var body = document.createElement('div');
        body.className = 'ai-chat-product-body';

        var title = document.createElement('a');
        title.className = 'ai-chat-product-title';
        title.href = product.url || '#';
        title.textContent = product.name || 'Product';
        body.appendChild(title);

        var meta = document.createElement('div');
        meta.className = 'ai-chat-product-meta';

        var price = document.createElement('span');
        price.className = 'ai-chat-product-price';
        price.textContent = product.price_display || '';
        meta.appendChild(price);

        var category = document.createElement('span');
        category.textContent = product.category || '';
        meta.appendChild(category);

        var stock = document.createElement('span');
        stock.className = 'ai-chat-stock';
        stock.textContent = product.available ? 'Available' : 'Unavailable';
        meta.appendChild(stock);
        body.appendChild(meta);

        if (product.reason) {
            var reason = document.createElement('div');
            reason.className = 'ai-chat-product-meta';
            reason.textContent = product.reason;
            body.appendChild(reason);
        }

        var actions = document.createElement('div');
        actions.className = 'ai-chat-product-actions';

        var view = document.createElement('a');
        view.className = 'ai-chat-product-action';
        view.href = product.url || '#';
        view.textContent = 'View';
        actions.appendChild(view);

        var add = document.createElement('button');
        add.type = 'button';
        add.className = 'ai-chat-product-action is-primary';
        if (product.can_add) {
            add.textContent = product.in_cart_quantity ? 'Add one more' : 'Add to cart';
            add.addEventListener('click', function () {
                addProduct(card, add, product);
            });
            actions.appendChild(add);
        } else {
            var signIn = document.createElement('a');
            signIn.className = 'ai-chat-product-action is-primary';
            signIn.href = signinUrl;
            signIn.textContent = 'Sign in to add';
            actions.appendChild(signIn);
        }

        if (product.in_cart_quantity) {
            var inCart = document.createElement('span');
            inCart.className = 'ai-chat-product-meta ai-chat-in-cart';
            inCart.textContent = 'In cart ×' + product.in_cart_quantity;
            actions.appendChild(inCart);
        }
        body.appendChild(actions);
        card.appendChild(body);

        var list = content.querySelector('.ai-chat-product-list');
        if (!list) {
            list = document.createElement('div');
            list.className = 'ai-chat-product-list';
            content.appendChild(list);
        }
        list.appendChild(card);
    }

    function renderProducts(content, products) {
        if (!Array.isArray(products) || !products.length) {
            return;
        }
        products.forEach(function (product) {
            renderProductCard(content, product);
        });
    }

    function renderOrder(content, order) {
        if (!order || !order.order_number) {
            return;
        }
        var card = document.createElement('section');
        card.className = 'ai-chat-order';

        var head = document.createElement('div');
        head.className = 'ai-chat-order-head';
        var number = document.createElement('strong');
        number.textContent = order.order_number;
        var status = document.createElement('span');
        status.className = 'ai-chat-order-status';
        status.textContent = order.status || '';
        head.appendChild(number);
        head.appendChild(status);
        card.appendChild(head);

        var meta = document.createElement('div');
        meta.className = 'ai-chat-order-meta';
        [order.total, order.payment_status, order.created_at].forEach(function (value) {
            if (!value) {
                return;
            }
            var span = document.createElement('span');
            span.textContent = value;
            meta.appendChild(span);
        });
        card.appendChild(meta);

        if (Array.isArray(order.items) && order.items.length) {
            var list = document.createElement('ul');
            list.className = 'ai-chat-order-items';
            order.items.forEach(function (item) {
                var li = document.createElement('li');
                li.textContent = (item.name || 'Item') + ' ×' + (item.quantity || 1);
                list.appendChild(li);
            });
            card.appendChild(list);
        }

        if (order.detail_url) {
            var link = document.createElement('a');
            link.className = 'ai-chat-link';
            link.href = order.detail_url;
            link.textContent = 'View order details';
            card.appendChild(link);
        }
        content.appendChild(card);
    }

    function renderSuggestions(items) {
        if (!suggestions || !Array.isArray(items)) {
            return;
        }
        suggestions.textContent = '';
        items.slice(0, 5).forEach(function (text) {
            if (typeof text !== 'string' || !text.trim()) {
                return;
            }
            var chip = document.createElement('button');
            chip.type = 'button';
            chip.className = 'ai-chat-chip';
            chip.textContent = text;
            chip.addEventListener('click', function () {
                sendMessage(text);
            });
            suggestions.appendChild(chip);
        });
    }

    function renderResponse(data) {
        var content = appendMessage('assistant', data.reply || 'I could not complete that request.');
        appendNotice(content, data.notice);
        renderProducts(content, data.products);
        renderOrder(content, data.order);
        renderLinks(content, data.links);
        if (data.action && data.action.type === 'signin_required' && data.signin_url && !(data.links || []).length) {
            renderLinks(content, [{ label: 'Sign in to continue', url: data.signin_url, icon: 'fas fa-right-to-bracket' }]);
        }
        renderSuggestions(data.suggestions);
        setStatus(data.ai_available !== false);
        updateCartCounts(data.cart_count);
        scrollMessages();
    }

    function sendMessage(message) {
        var text = (message || input.value || '').trim();
        if (!text || isLoading) {
            return;
        }
        if (!panel.hidden) {
            // Keep focus in the conversation while the local model is thinking.
            input.focus();
        } else {
            openChat('');
        }

        appendMessage('user', text);
        input.value = '';
        resizeInput();
        var typing = appendTyping();
        setLoading(true);

        var controller = new AbortController();
        var timeout = window.setTimeout(function () {
            controller.abort();
        }, 95000);

        fetch(chatUrl, {
            method: 'POST',
            credentials: 'same-origin',
            signal: controller.signal,
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken()
            },
            body: JSON.stringify({ message: text })
        }).then(function (response) {
            return response.json().catch(function () {
                return {};
            }).then(function (data) {
                return { response: response, data: data };
            });
        }).then(function (result) {
            if (typing) {
                typing.remove();
            }
            if (!result.response.ok) {
                var error = result.data && result.data.error ? result.data.error : 'The assistant could not answer that right now.';
                appendMessage('assistant', error);
                return;
            }
            renderResponse(result.data || {});
        }).catch(function (error) {
            if (typing) {
                typing.remove();
            }
            var message = error && error.name === 'AbortError'
                ? 'The local model took too long to answer. Please try again.'
                : 'I could not reach the assistant. Check the connection and try again.';
            appendMessage('assistant', message);
            setStatus(false);
        }).finally(function () {
            window.clearTimeout(timeout);
            setLoading(false);
            input.focus();
            scrollMessages();
        });
    }

    toggle.addEventListener('click', function () {
        if (panel.hidden) {
            openChat('');
        } else {
            closeChat();
        }
    });

    if (closeButton) {
        closeButton.addEventListener('click', closeChat);
    }

    document.addEventListener('keydown', function (event) {
        if (event.key === 'Escape' && !panel.hidden) {
            closeChat();
        }
    });

    form.addEventListener('submit', function (event) {
        event.preventDefault();
        sendMessage(input.value);
    });

    input.addEventListener('input', resizeInput);
    input.addEventListener('keydown', function (event) {
        if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault();
            sendMessage(input.value);
        }
    });

    document.addEventListener('click', function (event) {
        var trigger = event.target.closest('[data-ai-open]');
        if (!trigger) {
            return;
        }
        event.preventDefault();
        openChat(trigger.getAttribute('data-ai-prompt') || '');
    });

    document.querySelectorAll('[data-ai-prompt]').forEach(function (chip) {
        if (chip.closest('[data-ai-suggestions]')) {
            chip.addEventListener('click', function () {
                sendMessage(chip.getAttribute('data-ai-prompt') || '');
            });
        }
    });

    if (input.value) {
        resizeInput();
    }
})();

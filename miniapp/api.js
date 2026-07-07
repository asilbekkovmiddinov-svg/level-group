async function getWallet() {
    if (!TELEGRAM_ID) {
        return null;
    }

    return await api(`/wallet/${TELEGRAM_ID}`);
}


async function registerUser() {
    if (!TELEGRAM_ID) {
        return null;
    }

    return await api("/user/register", "POST", {
        telegram_id: TELEGRAM_ID,
        first_name: FIRST_NAME || "User",
        username: USERNAME || null,
        language: "uz",
    });
}


async function updateUserSeen() {
    if (!TELEGRAM_ID) {
        return null;
    }

    return await api(`/user/${TELEGRAM_ID}/seen`, "POST");
}


async function getOpenP2POrders(orderType) {
    return await api(`/p2p/open?order_type=${orderType}`);
}


async function getMyP2POrders() {
    return await api(`/p2p/my/${TELEGRAM_ID}`);
}


async function getMyP2PTrades() {
    return await api(`/p2p/trades/my/${TELEGRAM_ID}`);
}


async function getP2PHistory(status = "") {
    const query = status ? `?status=${status}` : "";
    return await api(`/p2p/history/${TELEGRAM_ID}${query}`);
}


async function getWheelStatus() {
    return await api(`/wheel/status/${TELEGRAM_ID}`);
}

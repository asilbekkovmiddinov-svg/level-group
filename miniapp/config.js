const API_URL = "https://level-backend-jocker7005.waw0.amvera.tech";

const tg = window.Telegram.WebApp;

tg.ready();
tg.expand();

const user = tg.initDataUnsafe.user || {};

const TELEGRAM_ID = user.id || 0;
const FIRST_NAME = user.first_name || "";
const USERNAME = user.username || "";

async function api(path, method = "GET", body = null) {
    const options = {
        method: method,
        headers: {
            "Content-Type": "application/json",
        },
    };

    if (body) {
        options.body = JSON.stringify(body);
    }

    const response = await fetch(API_URL + path, options);

    return await response.json();
}

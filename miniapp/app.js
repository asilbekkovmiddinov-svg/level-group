const loader = document.getElementById("loader");
const app = document.getElementById("app");

const efcBalance = document.getElementById("efcBalance");
const uzsBalance = document.getElementById("uzsBalance");

function formatMoney(value) {
    const number = Number(value || 0);

    return number.toLocaleString("uz-UZ", {
        maximumFractionDigits: 2,
    });
}

function showLoader() {
    loader.classList.remove("hidden");
    app.classList.add("hidden");
}

function hideLoader() {
    loader.classList.add("hidden");
    app.classList.remove("hidden");
}

async function loadWallet() {
    const result = await getWallet();

    if (!result || result.success === false) {
        efcBalance.textContent = "0";
        uzsBalance.textContent = "0";
        return;
    }

    const wallet = result.data || result;

    efcBalance.textContent = formatMoney(wallet.efc_balance);
    uzsBalance.textContent = formatMoney(wallet.uzs_balance);
}

function setupButtons() {
    document.querySelectorAll("[data-page]").forEach((button) => {
        button.addEventListener("click", () => {
            const page = button.dataset.page;

            if (page === "wallet") {
                loadWallet();
                tg.showAlert("Hamyon yangilandi.");
                return;
            }

            if (page === "p2p") {
                tg.showAlert("P2P WebApp sahifasi keyingi bosqichda qo‘shiladi.");
                return;
            }

            if (page === "wheel") {
                tg.showAlert("Baraban WebApp sahifasi keyingi bosqichda qo‘shiladi.");
                return;
            }

            if (page === "profile") {
                tg.showAlert("Profil WebApp sahifasi keyingi bosqichda qo‘shiladi.");
            }
        });
    });
}

async function initApp() {
    showLoader();

    try {
        await registerUser();
        await updateUserSeen();
        await loadWallet();
        setupButtons();
    } catch (error) {
        console.error(error);
        tg.showAlert("Mini App yuklanishda xatolik yuz berdi.");
    } finally {
        hideLoader();
    }
}

initApp();

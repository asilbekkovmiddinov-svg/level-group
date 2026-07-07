window.addEventListener("load", async () => {
    Loader.show();

    try {
        await registerUser();
        await updateUserSeen();

        Navbar.init();

        bindMenuButtons();

        await loadHome();

    } catch (error) {
        console.error(error);

        Modal.error(
            "Mini App yuklanishda xatolik yuz berdi."
        );
    }

    Loader.hide();
});


function bindMenuButtons() {

    document.querySelectorAll(".menu-card").forEach((button) => {

        button.addEventListener("click", async () => {

            const page = button.dataset.page;

            await openPage(page);

        });

    });

}


async function openPage(page) {

    switch (page) {

        case "shop":

            await loadShopPage();

            break;

        case "p2p":

            await loadP2PPage();

            break;

        case "wheel":

            await loadWheelPage();

            break;

        case "profile":

            await loadProfilePage();

            break;

        default:

            await loadHome();

    }

}


async function loadHome() {

    await loadWalletPage();

}

async function refreshCurrentPage() {

    switch (Navbar.currentPage) {

        case "home":
            await loadHome();
            break;

        case "shop":
            await loadShopPage();
            break;

        case "p2p":
            await loadP2PPage();
            break;

        case "wheel":
            await loadWheelPage();
            break;

        case "orders":
            await loadOrdersPage();
            break;

        case "profile":
            await loadProfilePage();
            break;

        default:
            await loadHome();
    }

}


async function refreshEverything() {

    Loader.show();

    try {

        await updateUserSeen();

        await refreshCurrentPage();

    } catch (error) {

        console.error(error);

        Modal.error(
            "Ma'lumotlarni yangilab bo'lmadi."
        );

    }

    Loader.hide();

}


Telegram.WebApp.onEvent(
    "themeChanged",
    () => {

        console.log("Theme changed");

    }
);


Telegram.WebApp.onEvent(
    "viewportChanged",
    () => {

        console.log("Viewport changed");

    }
);


setInterval(async () => {

    try {

        await updateUserSeen();

    } catch (e) {

        console.log(e);

    }

}, 60000);


setInterval(async () => {

    try {

        if (Navbar.currentPage === "home") {

            await loadWalletPage();

        }

    } catch (e) {

        console.log(e);

    }

}, 30000);

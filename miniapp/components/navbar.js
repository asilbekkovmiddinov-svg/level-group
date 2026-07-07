const Navbar = {
    currentPage: "home",

    setActive(page) {
        this.currentPage = page;

        document.querySelectorAll(".nav-btn").forEach((button) => {
            button.classList.remove("active");
        });

        const active = document.querySelector(
            `.nav-btn[data-page="${page}"]`
        );

        if (active) {
            active.classList.add("active");
        }
    },

    async open(page) {
        this.setActive(page);

        switch (page) {
            case "home":
                await refreshWallet();
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
                tg.showAlert("Bo'lim topilmadi.");
        }
    },

    init() {
        document.querySelectorAll(".nav-btn").forEach((button) => {
            button.addEventListener("click", () => {
                this.open(button.dataset.page);
            });
        });
    }
};

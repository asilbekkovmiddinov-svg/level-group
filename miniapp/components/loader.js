const Loader = {

    show() {
        const loader = document.getElementById("loader");
        const app = document.getElementById("app");

        if (loader) {
            loader.classList.remove("hidden");
        }

        if (app) {
            app.classList.add("hidden");
        }
    },

    hide() {
        const loader = document.getElementById("loader");
        const app = document.getElementById("app");

        if (loader) {
            loader.classList.add("hidden");
        }

        if (app) {
            app.classList.remove("hidden");
        }
    },

    async run(task) {
        try {
            this.show();

            await task();

        } finally {
            this.hide();
        }
    }

};

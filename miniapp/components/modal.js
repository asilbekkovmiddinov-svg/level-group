const Modal = {

    alert(title, message) {
        tg.showAlert(
            `${title}\n\n${message}`
        );
    },

    success(message) {
        tg.showAlert(
            `✅ ${message}`
        );
    },

    error(message) {
        tg.showAlert(
            `❌ ${message}`
        );
    },

    confirm(message, callback) {
        tg.showConfirm(
            message,
            (ok) => {
                if (ok && callback) {
                    callback();
                }
            }
        );
    },

    copy(text) {
        navigator.clipboard.writeText(text);

        tg.showAlert(
            "📋 Nusxalandi."
        );
    }

};

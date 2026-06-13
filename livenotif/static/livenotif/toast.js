document.addEventListener("DOMContentLoaded", function () {

    const container = document.getElementById("livetracker-toast-container");

    container.querySelectorAll(".lt-toast").forEach((toast, index) => {

        setTimeout(() => {
            toast.classList.remove("translate-x-10", "opacity-0");
        }, 50 * index);  // staggering effect

        const id = toast.dataset.toastId;

        toast.querySelector(".lt-ignore").addEventListener("click", () => {
            fetch(`/toast-action/${id}/ignored/`);
            toast.remove();
        });

        toast.querySelector(".lt-action").addEventListener("click", () => {
            fetch(`/toast-action/${id}/action/`);
            toast.remove();
        });

    });

});

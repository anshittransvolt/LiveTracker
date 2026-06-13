
        // Initialize Lucide icons
        lucide.createIcons();

        const pwd = document.getElementById("password");
        const toggle = document.getElementById("togglePassword");
        const eyeOpen = document.getElementById("eyeOpen");
        const eyeClosed = document.getElementById("eyeClosed");
        const loginForm = document.querySelector("form");
        const loginButton = document.getElementById("loginButton");
        const loadingSpinner = document.getElementById("loadingSpinner");
        const loginIcon = document.getElementById("loginIcon");
        const buttonText = document.getElementById("buttonText");
        const captchaHint = document.getElementById("captchaHint");

        // Collapsible form toggle
        const toggleLoginFormBtn = document.getElementById("toggleLoginForm");
        const loginFormContainer = document.getElementById("loginFormContainer");
        const chevronIcon = document.getElementById("chevronIcon");

        if (toggleLoginFormBtn && loginFormContainer) {
          toggleLoginFormBtn.addEventListener("click", function () {
            const isHidden = loginFormContainer.classList.contains("hidden");
            
            if (isHidden) {
              loginFormContainer.classList.remove("hidden");
              chevronIcon.style.transform = "rotate(180deg)";
            } else {
              loginFormContainer.classList.add("hidden");
              chevronIcon.style.transform = "rotate(0deg)";
            }
            
            // Reinitialize Lucide icons for the newly shown form
            lucide.createIcons();
          });
        }

        // Password visibility toggle
        if (toggle && pwd) {
          toggle.addEventListener("click", function () {
            const isPassword = pwd.getAttribute("type") === "password";
            pwd.setAttribute("type", isPassword ? "text" : "password");
            eyeOpen.classList.toggle("hidden", !isPassword);
            eyeClosed.classList.toggle("hidden", isPassword);
            // keep focus on the input after toggle
            pwd.focus();
          });
        }

        // Form submission loading state
        if (loginForm && loginButton) {
          loginForm.addEventListener("submit", function (e) {
            if (hasCaptchaWidget() && !isCaptchaVerified()) {
              e.preventDefault();
              updateLoginButtonForCaptcha();
              return;
            }

            // Show loading state
            loginButton.disabled = true;
            loginButton.classList.add("opacity-75", "cursor-not-allowed");
            loginButton.classList.remove("hover:bg-blue-700");

            // Show spinner and hide login icon
            loadingSpinner.classList.remove("hidden");
            loginIcon.classList.add("hidden");
            buttonText.textContent = "Signing in...";

            // Optional: Add a minimum loading time to show the spinner
            setTimeout(function () {
              if (!loginForm.checkValidity()) {
                resetLoginButton();
              }
            }, 100);
          });
        }

        // Reset login button function
        function resetLoginButton() {
          if (loginButton) {
            loadingSpinner.classList.add("hidden");
            loginIcon.classList.remove("hidden");
            buttonText.textContent = "Login";
            updateLoginButtonForCaptcha();
          }
        }

        function getCaptchaResponseInput() {
          return document.querySelector('textarea[name="g-recaptcha-response"]');
        }

        function hasCaptchaWidget() {
          return !!document.querySelector(".g-recaptcha") || !!getCaptchaResponseInput();
        }

        function isCaptchaVerified() {
          const captchaInput = getCaptchaResponseInput();
          return !!(captchaInput && captchaInput.value && captchaInput.value.trim().length > 0);
        }

        function updateLoginButtonForCaptcha() {
          if (!loginButton) return;

          // If captcha is not present on the page, preserve normal login behavior.
          if (!hasCaptchaWidget()) {
            loginButton.disabled = false;
            loginButton.classList.remove("opacity-75", "cursor-not-allowed");
            loginButton.classList.add("hover:bg-blue-700");
            if (captchaHint) captchaHint.classList.add("hidden");
            return;
          }

          const verified = isCaptchaVerified();
          loginButton.disabled = !verified;

          if (verified) {
            loginButton.classList.remove("opacity-75", "cursor-not-allowed");
            loginButton.classList.add("hover:bg-blue-700");
            if (captchaHint) captchaHint.classList.add("hidden");
          } else {
            loginButton.classList.add("opacity-75", "cursor-not-allowed");
            loginButton.classList.remove("hover:bg-blue-700");
            if (captchaHint) captchaHint.classList.remove("hidden");
          }
        }

        // Keep login button state in sync with captcha interaction.
        setInterval(updateLoginButtonForCaptcha, 400);
        updateLoginButtonForCaptcha();

        // Reset button state if there are validation errors
        window.addEventListener("load", function () {
          resetLoginButton();
        });

        // Handle browser back button
        window.addEventListener("pageshow", function () {
          resetLoginButton();
        });
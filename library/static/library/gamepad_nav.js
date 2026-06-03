// gamepad_nav.js - Global Spatial Navigation for Gamepads

let globalGamepadState = {};
let lastNavTime = 0;
const NAV_COOLDOWN = 150; // ms between d-pad moves

function getFocusableElements() {
    const elements = Array.from(document.querySelectorAll('a[href], button, input, select, textarea, [tabindex]:not([tabindex="-1"])'));
    return elements.filter(el => {
        const rect = el.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0 && window.getComputedStyle(el).visibility !== 'hidden';
    });
}

function getCenter(rect) {
    return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
}

function navigate(direction) {
    const now = Date.now();
    if (now - lastNavTime < NAV_COOLDOWN) return;
    
    const elements = getFocusableElements();
    if (elements.length === 0) return;

    let current = document.activeElement;
    if (!elements.includes(current)) {
        // If nothing is focused, focus the first element (usually top-left)
        elements[0].focus();
        lastNavTime = now;
        return;
    }

    const currentRect = current.getBoundingClientRect();
    const currentCenter = getCenter(currentRect);

    let bestMatch = null;
    let minDistance = Infinity;

    elements.forEach(el => {
        if (el === current) return;
        const rect = el.getBoundingClientRect();
        const center = getCenter(rect);

        let isValid = false;
        let distance = 0;

        // Calculate angle and distance
        const dx = center.x - currentCenter.x;
        const dy = center.y - currentCenter.y;
        const absDx = Math.abs(dx);
        const absDy = Math.abs(dy);

        if (direction === 'UP' && dy < 0 && absDy > absDx) isValid = true;
        if (direction === 'DOWN' && dy > 0 && absDy > absDx) isValid = true;
        if (direction === 'LEFT' && dx < 0 && absDx > absDy) isValid = true;
        if (direction === 'RIGHT' && dx > 0 && absDx > absDy) isValid = true;

        if (isValid) {
            // Euclidean distance
            distance = Math.sqrt(dx * dx + dy * dy);
            // Weight the distance heavily by the primary axis to prefer straight lines
            if (direction === 'UP' || direction === 'DOWN') distance += absDx * 2;
            if (direction === 'LEFT' || direction === 'RIGHT') distance += absDy * 2;

            if (distance < minDistance) {
                minDistance = distance;
                bestMatch = el;
            }
        }
    });

    if (bestMatch) {
        bestMatch.focus();
        // Ensure it's scrolled into view nicely
        bestMatch.scrollIntoView({ behavior: 'smooth', block: 'center' });
        lastNavTime = now;
    }
}

function pollGlobalGamepads() {
    const gamepads = navigator.getGamepads ? navigator.getGamepads() : [];
    for (let i = 0; i < gamepads.length; i++) {
        const gp = gamepads[i];
        if (gp) {
            // A Button (0) - Click
            if (gp.buttons[0].pressed && !globalGamepadState.btn0) {
                if (document.activeElement) document.activeElement.click();
            }
            globalGamepadState.btn0 = gp.buttons[0].pressed;

            // B Button (1) - Back
            if (gp.buttons[1].pressed && !globalGamepadState.btn1) {
                window.history.back();
            }
            globalGamepadState.btn1 = gp.buttons[1].pressed;

            // D-Pad Navigation (Buttons 12, 13, 14, 15)
            // Or Analog Stick threshold
            const axesX = gp.axes[0];
            const axesY = gp.axes[1];

            if ((gp.buttons[12] && gp.buttons[12].pressed) || axesY < -0.5) navigate('UP');
            else if ((gp.buttons[13] && gp.buttons[13].pressed) || axesY > 0.5) navigate('DOWN');
            else if ((gp.buttons[14] && gp.buttons[14].pressed) || axesX < -0.5) navigate('LEFT');
            else if ((gp.buttons[15] && gp.buttons[15].pressed) || axesX > 0.5) navigate('RIGHT');
            else {
                // Reset cooldown if everything released
                lastNavTime = 0; 
            }
        }
    }
    requestAnimationFrame(pollGlobalGamepads);
}

// Only start global polling if we are NOT on a playback page
// Playback pages have their own dedicated gamepad script
document.addEventListener("DOMContentLoaded", () => {
    if (!document.body.classList.contains('playback-page')) {
        window.addEventListener("gamepadconnected", () => {
            pollGlobalGamepads();
        });
        
        // Start polling immediately in case controller was already connected
        pollGlobalGamepads();
    }
});

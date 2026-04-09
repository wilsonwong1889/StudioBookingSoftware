import { api } from "../api.js?v=20260401r";
import { elements, toggleHidden } from "../dom.js?v=20260401r";
import { setState } from "../state.js?v=20260401r";

let stripeClient = null;
let stripeElements = null;
let paymentElement = null;
let activePaymentSession = null;
let paymentDeadlineTimer = null;
let reloadBookingDetailAction = null;

function formatBookingDate(value) {
  return new Intl.DateTimeFormat("en-US", {
    dateStyle: "full",
    timeStyle: "short",
  }).format(new Date(value));
}

function formatCurrency(cents, currency) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: currency || "CAD",
  }).format((cents || 0) / 100);
}

function formatCountdown(seconds) {
  const safeSeconds = Math.max(0, seconds || 0);
  const minutes = Math.floor(safeSeconds / 60);
  const remainingSeconds = safeSeconds % 60;
  return `${minutes}:${String(remainingSeconds).padStart(2, "0")}`;
}

function formatDuration(minutes) {
  const hours = minutes / 60;
  return `${hours} hour${hours === 1 ? "" : "s"}`;
}

function buildPaymentSuccessUrl(bookingId) {
  const successUrl = new URL("/payment-success", window.location.origin);
  successUrl.searchParams.set("id", bookingId);
  return successUrl;
}

function renderStaffImage(photoUrl, label) {
  if (photoUrl) {
    return `<img class="staff-profile-image" src="${photoUrl}" alt="${label}" loading="lazy" />`;
  }
  return `<div class="staff-profile-image staff-avatar-fallback">${label.slice(0, 1).toUpperCase()}</div>`;
}

function renderTagGroup(label, values = []) {
  if (!values.length) {
    return "";
  }

  return `
    <div class="staff-tag-group">
      <span>${label}</span>
      <div class="preview-pill-row">
        ${values.map((value) => `<span class="pill">${value}</span>`).join("")}
      </div>
    </div>
  `;
}

function clearPaymentElement() {
  if (paymentElement) {
    paymentElement.unmount();
    paymentElement = null;
  }
  stripeElements = null;
  stripeClient = null;
  activePaymentSession = null;
}

function clearPaymentDeadlineTimer() {
  if (paymentDeadlineTimer) {
    window.clearInterval(paymentDeadlineTimer);
    paymentDeadlineTimer = null;
  }
}

function getPaymentDeadlineElement() {
  return document.getElementById("booking-payment-deadline");
}

function renderPaymentDeadline(booking) {
  const deadlineElement = getPaymentDeadlineElement();
  if (!deadlineElement) {
    return;
  }

  clearPaymentDeadlineTimer();

  if (booking.status !== "PendingPayment" || !booking.payment_expires_at) {
    deadlineElement.classList.add("hidden");
    deadlineElement.textContent = "";
    return;
  }

  const updateCountdown = () => {
    const secondsRemaining = Math.max(
      0,
      Math.floor((new Date(booking.payment_expires_at).getTime() - Date.now()) / 1000),
    );
    deadlineElement.classList.remove("hidden");
    deadlineElement.className = "panel-copy payment-deadline-note";
    deadlineElement.textContent = `This spot is saved until ${formatBookingDate(booking.payment_expires_at)}. Time left: ${formatCountdown(secondsRemaining)}.`;

    if (secondsRemaining <= 0) {
      clearPaymentDeadlineTimer();
      if (reloadBookingDetailAction) {
        void reloadBookingDetailAction("Your 5-minute payment window expired.");
      }
    }
  };

  updateCountdown();
  paymentDeadlineTimer = window.setInterval(updateCountdown, 1000);
}

async function loadPaymentSession(booking) {
  const session = await api.getBookingPaymentSession(booking.id);
  activePaymentSession = session;
  return session;
}

async function mountStripePaymentForm(session) {
  if (!window.Stripe || !session.stripe_publishable_key) {
    throw new Error("Stripe publishable key is not configured");
  }

  clearPaymentElement();
  stripeClient = window.Stripe(session.stripe_publishable_key);
  stripeElements = stripeClient.elements({ clientSecret: session.payment_client_secret });
  paymentElement = stripeElements.create("payment");
  paymentElement.mount("#booking-payment-element");
  toggleHidden(elements.bookingPaymentElement, false);
}

function renderPaymentPanel(state, booking) {
  if (!elements.bookingPaymentPanel || !elements.bookingPaymentCopy || !elements.bookingPaymentControls) {
    return;
  }

  const isPending = booking.status === "PendingPayment";
  const canAdminWaivePayment = isPending && Boolean(state.currentUser?.is_admin);
  toggleHidden(elements.bookingPaymentPanel, !isPending);
  if (!isPending) {
    clearPaymentElement();
    return;
  }

  elements.bookingPaymentCopy.textContent = state.message || "Load the payment session to continue checkout.";
  elements.bookingPaymentControls.innerHTML = `
    <button class="ghost-button" type="button" data-booking-detail-action="load-payment" data-booking-id="${booking.id}">
      Load payment
    </button>
    ${
      canAdminWaivePayment
        ? `<button class="ghost-button" type="button" data-booking-detail-action="waive-payment" data-booking-id="${booking.id}">
      Skip Stripe as admin
    </button>`
        : ""
    }
    <button class="primary-button hidden" type="button" data-booking-detail-action="confirm-payment" data-booking-id="${booking.id}">
      Confirm payment
    </button>
  `;

  if (activePaymentSession?.booking_id === booking.id) {
    const confirmButton = elements.bookingPaymentControls.querySelector("[data-booking-detail-action='confirm-payment']");
    if (confirmButton && activePaymentSession.payment_backend === "stripe") {
      confirmButton.classList.remove("hidden");
    }
    if (activePaymentSession.payment_backend !== "stripe") {
      elements.bookingPaymentCopy.textContent =
        "Stub payment mode is active. Switch PAYMENT_BACKEND to stripe and configure Stripe keys to use live test checkout.";
    }
  } else {
    toggleHidden(elements.bookingPaymentElement, true);
  }
}

function renderStaffAssignments(booking) {
  if (!elements.bookingDetailStaffList) {
    return;
  }

  const assignments = booking.staff_assignments || [];
  elements.bookingDetailStaffList.innerHTML = assignments.length
    ? assignments
        .map(
          (assignment) => `
            <article class="staff-profile-card">
              <div class="staff-profile-card-top">
                ${renderStaffImage(assignment.photo_url, assignment.name)}
                <div class="staff-option-copy">
                  <strong>${assignment.name}</strong>
                  <span>${assignment.description || "Added to this booking."}</span>
                </div>
              </div>
              <strong class="staff-option-price">${formatCurrency(assignment.add_on_price_cents, booking.currency)}</strong>
              <div class="staff-option-copy">
                ${renderTagGroup("Skills", assignment.skills || [])}
                ${renderTagGroup("Talents", assignment.talents || [])}
              </div>
            </article>
          `,
        )
        .join("")
    : '<div class="empty-state">No extra staff add-ons were attached to this booking.</div>';
}

export function initBookingDetailView(actions) {
  if (!elements.bookingDetailActions) {
    return;
  }

  reloadBookingDetailAction = actions?.reloadBookingDetail || null;

  const handleAction = async (event) => {
    const button = event.target.closest("[data-booking-detail-action]");
    if (!button) {
      return;
    }

    const action = button.dataset.bookingDetailAction;

    try {
      if (action === "cancel") {
        setState({ message: "Cancelling booking..." });
        const booking = await api.cancelBooking(button.dataset.bookingId, { reason: "Cancelled by user" });
        clearPaymentElement();
        setState({ selectedBooking: booking, message: "Booking cancelled." });
        if (actions?.reloadBookingDetail) {
          await actions.reloadBookingDetail("Booking detail refreshed.");
        }
        return;
      }

      if (action === "load-payment") {
        setState({ message: "Loading payment session..." });
        const booking = await api.getBooking(button.dataset.bookingId);
        const session = await loadPaymentSession(booking);
        if (session.payment_backend === "stripe") {
          await mountStripePaymentForm(session);
          setState({ message: "Payment form loaded." });
        } else {
          toggleHidden(elements.bookingPaymentElement, true);
          setState({ message: "Stub payment session loaded. Configure Stripe to continue with live test checkout." });
        }
        if (actions?.reloadBookingDetail) {
          await actions.reloadBookingDetail("Payment session ready.");
        }
        return;
      }

      if (action === "confirm-payment") {
        if (!stripeClient || !stripeElements || !activePaymentSession) {
          throw new Error("Load the payment session first");
        }
        setState({ message: "Confirming payment..." });
        const successUrl = buildPaymentSuccessUrl(activePaymentSession.booking_id);
        const submitResult = await stripeElements.submit();
        if (submitResult?.error) {
          throw new Error(submitResult.error.message || "Payment details are incomplete");
        }
        const result = await stripeClient.confirmPayment({
          elements: stripeElements,
          clientSecret: activePaymentSession.payment_client_secret,
          confirmParams: {
            return_url: successUrl.toString(),
          },
          redirect: "if_required",
        });
        if (result.error) {
          throw new Error(result.error.message || "Payment confirmation failed");
        }
        window.location.assign(successUrl.toString());
        return;
      }

      if (action === "waive-payment") {
        const confirmed = window.confirm("Skip Stripe and mark this booking free?");
        if (!confirmed) {
          return;
        }
        setState({ message: "Skipping Stripe and marking booking free..." });
        const booking = await api.adminWaiveBookingPayment(button.dataset.bookingId);
        clearPaymentElement();
        setState({ selectedBooking: booking, message: "Booking marked free." });
        window.location.assign(buildPaymentSuccessUrl(booking.id).toString());
      }
    } catch (error) {
      setState({ message: error.message });
    }
  };

  elements.bookingDetailActions.addEventListener("click", handleAction);
  elements.bookingPaymentControls?.addEventListener("click", handleAction);
}

export function renderBookingDetailView(state) {
  if (!elements.bookingDetailEmpty || !elements.bookingDetailCard) {
    return;
  }

  const booking = state.selectedBooking;
  const hasBooking = Boolean(booking);
  toggleHidden(elements.bookingDetailEmpty, hasBooking);
  toggleHidden(elements.bookingDetailCard, !hasBooking);

  if (!booking) {
    clearPaymentDeadlineTimer();
    clearPaymentElement();
    return;
  }

  elements.bookingDetailTitle.textContent = `${booking.status} • ${booking.booking_code}`;
  elements.bookingDetailWindow.textContent = `${formatBookingDate(booking.start_time)} to ${formatBookingDate(booking.end_time)}`;
  elements.bookingDetailMeta.innerHTML = `
    <span class="pill">${formatCurrency(booking.price_cents, booking.currency)}</span>
    <span class="pill">${formatDuration(booking.duration_minutes)}</span>
    <span class="pill">${booking.currency}</span>
    <span class="pill">${(booking.staff_assignments || []).length} staff profile${(booking.staff_assignments || []).length === 1 ? "" : "s"}</span>
    ${booking.checked_in_at ? `<span class="pill">Checked in ${formatBookingDate(booking.checked_in_at)}</span>` : ""}
    ${booking.payment_intent_id ? `<span class="pill">Payment ${booking.payment_intent_id}</span>` : ""}
  `;
  if (elements.bookingDetailNote) {
    elements.bookingDetailNote.textContent = booking.note
      ? `Booking notes: ${booking.note}`
      : "No booking notes added.";
  }
  renderStaffAssignments(booking);
  renderPaymentDeadline(booking);

  const canCancel = booking.status === "PendingPayment" || booking.status === "Paid";
  const canPay = booking.status === "PendingPayment";
  elements.bookingDetailActions.innerHTML = `
    ${canCancel ? `<button class="ghost-button" type="button" data-booking-detail-action="cancel" data-booking-id="${booking.id}">Cancel booking</button>` : ""}
    ${canPay ? `<button class="ghost-button" type="button" data-booking-detail-action="load-payment" data-booking-id="${booking.id}">Continue payment</button>` : ""}
  `;

  renderPaymentPanel(state, booking);
}

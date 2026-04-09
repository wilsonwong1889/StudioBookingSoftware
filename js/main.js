import { api } from "./api.js?v=20260401r";
import { CURRENT_PAGE, getSearchParam } from "./config.js?v=20260401r";
import { setState, state, subscribe, persistToken } from "./state.js?v=20260401r";
import { initAdminView, renderAdminView } from "./views/admin.js?v=20260408f";
import { initAuthView, renderAuthView } from "./views/auth.js?v=20260401y";
import { initBookingDetailView, renderBookingDetailView } from "./views/booking-detail.js?v=20260408h";
import { initBookingsView, renderBookingsView } from "./views/bookings.js?v=20260408g";
import { initInfoView, renderInfoView } from "./views/info.js?v=20260401r";
import { initPaymentSuccessView, renderPaymentSuccessView } from "./views/payment-success.js?v=20260408c";
import { initProfileView, renderProfileView } from "./views/profile.js?v=20260401y";
import { initRoomBookingView, renderRoomBookingView } from "./views/room-booking.js?v=20260401u";
import { initRoomDetailView, renderRoomDetailView } from "./views/room-detail.js?v=20260401r";
import { initRoomsView, renderRoomsView } from "./views/rooms.js?v=20260408e";
import { initStaffDirectoryView, renderStaffDirectoryView } from "./views/staff-directory.js?v=20260401v";
import { renderStatus } from "./views/status.js?v=20260401r";

const PAGE_DATA_REQUIREMENTS = {
  home: { rooms: false, bookings: false, admin: false, selectedRoom: false, selectedBooking: false },
  account: { rooms: false, bookings: false, admin: false, selectedRoom: false, selectedBooking: false },
  contact: { rooms: false, bookings: false, admin: false, selectedRoom: false, selectedBooking: false, publicStaff: false },
  faq: { rooms: false, bookings: false, admin: false, selectedRoom: false, selectedBooking: false, publicStaff: false },
  info: { rooms: false, bookings: false, admin: false, selectedRoom: false, selectedBooking: false, publicStaff: false },
  rooms: { rooms: true, bookings: false, admin: false, selectedRoom: false, selectedBooking: false },
  room: { rooms: false, bookings: false, admin: false, selectedRoom: true, selectedBooking: false },
  reserve: { rooms: false, bookings: false, admin: false, selectedRoom: true, selectedBooking: false },
  staff: { rooms: false, bookings: false, admin: false, selectedRoom: false, selectedBooking: false, publicStaff: true },
  bookings: { rooms: true, bookings: true, admin: false, selectedRoom: false, selectedBooking: false },
  booking: { rooms: false, bookings: false, admin: false, selectedRoom: false, selectedBooking: true },
  "payment-success": { rooms: false, bookings: false, admin: false, selectedRoom: false, selectedBooking: true },
  admin: { rooms: true, bookings: false, admin: true, selectedRoom: false, selectedBooking: false },
};

function currentRequirements() {
  return PAGE_DATA_REQUIREMENTS[CURRENT_PAGE] || PAGE_DATA_REQUIREMENTS.home;
}

function renderApp(currentState) {
  renderStatus(currentState);
  renderAuthView(currentState);
  renderAdminView(currentState);
  renderBookingsView(currentState);
  renderBookingDetailView(currentState);
  renderInfoView(currentState);
  renderPaymentSuccessView(currentState);
  renderProfileView(currentState);
  renderRoomBookingView(currentState);
  renderRoomDetailView(currentState);
  renderRoomsView(currentState);
  renderStaffDirectoryView(currentState);
}

function resetScopedData() {
  const requirements = currentRequirements();
  const patch = {};

  if (!requirements.rooms) {
    patch.rooms = [];
    patch.roomAvailabilityPreview = {};
    patch.showInactiveRooms = false;
  }
  if (!requirements.bookings) {
    patch.bookings = [];
    patch.availability = null;
  }
  if (!requirements.admin) {
    patch.adminBookings = [];
    patch.adminAnalytics = null;
    patch.adminActivity = [];
    patch.adminUsers = [];
    patch.adminTestCases = [];
    patch.adminStaffProfiles = [];
  }
  if (!requirements.publicStaff) {
    patch.publicStaffProfiles = [];
  }
  if (!requirements.selectedRoom) {
    patch.selectedRoom = null;
  }
  if (!requirements.selectedBooking) {
    patch.selectedBooking = null;
  }

  if (Object.keys(patch).length) {
    setState(patch);
  }
}

async function loadHealth() {
  try {
    const health = await api.getHealth();
    setState({ health, message: "Backend connected." });
  } catch (error) {
    setState({ health: false, message: error.message });
  }
}

async function refreshRooms(message) {
  if (!currentRequirements().rooms) {
    return;
  }

  try {
    const shouldIncludeInactive = Boolean(
      state.currentUser?.is_admin && state.showInactiveRooms,
    );
    const rooms = await api.getRooms(shouldIncludeInactive);
    setState({ rooms, message: message || "Rooms loaded." });
  } catch (error) {
    setState({ message: error.message });
  }
}

async function refreshBookings(message) {
  if (!currentRequirements().bookings) {
    return;
  }

  if (!state.token) {
    setState({ bookings: [], availability: null, message: message || "Signed out." });
    return;
  }

  try {
    const bookings = await api.getBookings();
    setState({ bookings, message: message || "Bookings loaded." });
  } catch (error) {
    setState({ message: error.message });
  }
}

async function refreshAdminBookings(message) {
  if (!currentRequirements().admin) {
    return;
  }

  if (!state.currentUser?.is_admin) {
    setState({ adminBookings: [], message: message || state.message });
    return;
  }

  try {
    const adminBookings = await api.adminLookupBookings({});
    setState({ adminBookings, message: message || "Admin bookings loaded." });
  } catch (error) {
    setState({ message: error.message });
  }
}

async function refreshAdminAnalytics(message) {
  if (!currentRequirements().admin) {
    return;
  }

  if (!state.currentUser?.is_admin) {
    setState({ adminAnalytics: null, message: message || state.message });
    return;
  }

  try {
    const adminAnalytics = await api.getAdminAnalyticsSummary();
    setState({ adminAnalytics, message: message || "Admin analytics loaded." });
  } catch (error) {
    setState({ message: error.message });
  }
}

async function refreshAdminActivity(message) {
  if (!currentRequirements().admin) {
    return;
  }

  if (!state.currentUser?.is_admin) {
    setState({ adminActivity: [], message: message || state.message });
    return;
  }

  try {
    const adminActivity = await api.getAdminActivity();
    setState({ adminActivity, message: message || "Admin activity loaded." });
  } catch (error) {
    setState({ message: error.message });
  }
}

async function refreshAdminUsers(message) {
  if (!currentRequirements().admin) {
    return;
  }

  if (!state.currentUser?.is_admin) {
    setState({ adminUsers: [], message: message || state.message });
    return;
  }

  try {
    const adminUsers = await api.getAdminUsers();
    setState({ adminUsers, message: message || "Accounts loaded." });
  } catch (error) {
    setState({ message: error.message });
  }
}

async function refreshAdminTestCases(message) {
  if (!currentRequirements().admin) {
    return;
  }

  if (!state.currentUser?.is_admin) {
    setState({ adminTestCases: [], message: message || state.message });
    return;
  }

  try {
    const adminTestCases = await api.getAdminTestCases();
    setState({ adminTestCases, message: message || "Backend test cases loaded." });
  } catch (error) {
    setState({ message: error.message });
  }
}

async function refreshAdminStaffProfiles(message) {
  if (!currentRequirements().admin) {
    return;
  }

  if (!state.currentUser?.is_admin) {
    setState({ adminStaffProfiles: [], message: message || state.message });
    return;
  }

  try {
    const adminStaffProfiles = await api.getAdminStaffProfiles();
    setState({ adminStaffProfiles, message: message || "Staff profiles loaded." });
  } catch (error) {
    setState({ message: error.message });
  }
}

async function refreshPublicStaffProfiles(message) {
  if (!currentRequirements().publicStaff) {
    return;
  }

  try {
    const publicStaffProfiles = await api.getPublicStaffProfiles();
    setState({ publicStaffProfiles, message: message || "Staff directory loaded." });
  } catch (error) {
    setState({ message: error.message });
  }
}

async function loadSelectedRoom(message) {
  if (!currentRequirements().selectedRoom) {
    return;
  }

  const roomId = getSearchParam("id");
  if (!roomId) {
    setState({ selectedRoom: null, message: "Room id is missing." });
    return;
  }

  try {
    const selectedRoom = await api.getRoom(roomId);
    setState({ selectedRoom, message: message || "Room loaded." });
  } catch (error) {
    setState({ selectedRoom: null, message: error.message });
  }
}

async function loadSelectedBooking(message) {
  if (!currentRequirements().selectedBooking) {
    return;
  }

  const bookingId = getSearchParam("id");
  if (!bookingId) {
    setState({ selectedBooking: null, message: "Booking id is missing." });
    return;
  }

  if (!state.token) {
    setState({ selectedBooking: null, message: "Log in to view booking details." });
    return;
  }

  try {
    const selectedBooking = await api.getBooking(bookingId);
    setState({ selectedBooking, message: message || "Booking loaded." });
  } catch (error) {
    setState({ selectedBooking: null, message: error.message });
  }
}

async function refreshAvailabilityAndBookings(message) {
  await refreshRooms(message);
  await refreshBookings(message);
  await refreshAdminBookings(message);
  await refreshAdminAnalytics(message);
  await refreshAdminActivity(message);
  await refreshAdminUsers(message);
  await refreshAdminTestCases(message);
  await refreshAdminStaffProfiles(message);
  await refreshPublicStaffProfiles(message);
  await loadSelectedBooking(message);

  if (!currentRequirements().bookings) {
    return;
  }

  const roomId = document.getElementById("booking-room-select")?.value;
  const date = document.getElementById("booking-date-input")?.value;
  if (!roomId || !date) {
    return;
  }

  try {
    const availability = await api.getAvailability(roomId, date);
    setState({ availability, message: message || "Booking state refreshed." });
  } catch (error) {
    setState({ availability: null, message: error.message });
  }
}

async function loadPageData(message) {
  const requirements = currentRequirements();

  if (requirements.rooms) {
    await refreshRooms(message || "Rooms ready.");
  }
  if (requirements.bookings) {
    await refreshBookings(message || "Bookings ready.");
  }
  if (requirements.admin) {
    await refreshAdminBookings(message || "Admin workspace ready.");
    await refreshAdminAnalytics(message || "Admin workspace ready.");
    await refreshAdminActivity(message || "Admin workspace ready.");
    await refreshAdminUsers(message || "Admin workspace ready.");
    await refreshAdminTestCases(message || "Admin workspace ready.");
    await refreshAdminStaffProfiles(message || "Admin workspace ready.");
  }
  if (requirements.publicStaff) {
    await refreshPublicStaffProfiles(message || "Staff page ready.");
  }
  if (requirements.selectedRoom) {
    await loadSelectedRoom(message || "Room ready.");
  }
  if (requirements.selectedBooking) {
    await loadSelectedBooking(message || "Booking ready.");
  }
}

async function refreshSession(message) {
  resetScopedData();

  if (!state.token) {
    setState({ currentUser: null, message: message || "Signed out." });
    await loadPageData("Public view loaded.");
    return;
  }

  try {
    const currentUser = await api.getMe();
    setState({ currentUser, message: message || "Session restored." });
    await loadPageData("Session ready.");
  } catch (error) {
    persistToken(null);
    setState({
      currentUser: null,
      bookings: [],
      adminBookings: [],
      adminAnalytics: null,
      adminActivity: [],
      adminUsers: [],
      adminTestCases: [],
      adminStaffProfiles: [],
      publicStaffProfiles: [],
      selectedRoom: null,
      selectedBooking: null,
      availability: null,
      message: error.message,
    });
    await loadPageData("Token cleared.");
  }
}

async function clearSession() {
  setState({
    currentUser: null,
    bookings: [],
    adminBookings: [],
    adminAnalytics: null,
    adminActivity: [],
    adminUsers: [],
    adminTestCases: [],
    adminStaffProfiles: [],
    publicStaffProfiles: [],
    selectedRoom: null,
    selectedBooking: null,
    availability: null,
    message: "Signed out.",
  });
  await loadPageData("Public view loaded.");
}

subscribe(renderApp);

initAdminView({ refreshAll: refreshAvailabilityAndBookings, getState: () => state });
initAuthView({ refreshSession, clearSession });
initBookingsView({ refreshAvailabilityAndBookings });
initBookingDetailView({ reloadBookingDetail: loadSelectedBooking });
initInfoView();
initPaymentSuccessView({ reloadPaymentSuccess: loadSelectedBooking });
initProfileView({ clearSession });
initRoomBookingView();
initRoomDetailView();
initRoomsView({ refreshRooms });
initStaffDirectoryView();

renderApp(state);
resetScopedData();
await loadHealth();
await refreshSession("Frontend ready.");

// Fake research results for the mock API. Prices are made up and every
// source_url points at example.com so nobody mistakes them for real quotes.
import type { Option, OptionKind, TripRequest } from "../types";

type ActivitySeed = {
  title: string;
  theme: 0 | 1 | 2;
  perPerson: number;
  kind?: OptionKind;
  minutes: number;
  estimate?: boolean;
};

type Profile = {
  match: RegExp;
  flightPerPerson: number;
  hotelPerRoomNight: number;
  /** Meals + local transport per person per day. Not an option; goes to "other". */
  dailyPerPerson: number;
  themes: [string, string, string];
  activities: ActivitySeed[];
  safety?: string;
};

const TOKYO: Profile = {
  match: /tokyo|japan|kyoto|osaka/i,
  flightPerPerson: 1450,
  hotelPerRoomNight: 185,
  dailyPerPerson: 75,
  themes: ["Temples and history", "Food and nightlife", "Day trips"],
  activities: [
    { title: "Senso-ji Temple and Asakusa walk", theme: 0, perPerson: 0, minutes: 120 },
    { title: "Meiji Jingu Shrine", theme: 0, perPerson: 0, minutes: 90 },
    { title: "Tokyo National Museum", theme: 0, perPerson: 8, minutes: 150 },
    { title: "Tea ceremony in Asakusa", theme: 0, perPerson: 45, minutes: 60 },
    { title: "Edo-Tokyo Museum", theme: 0, perPerson: 6, minutes: 120 },
    { title: "Tsukiji outer market food tour", theme: 1, perPerson: 95, kind: "food", minutes: 180 },
    { title: "Shinjuku izakaya crawl", theme: 1, perPerson: 120, kind: "food", minutes: 180, estimate: true },
    { title: "Shibuya Sky observation deck", theme: 1, perPerson: 18, minutes: 60 },
    { title: "Sushi-making class", theme: 1, perPerson: 85, kind: "food", minutes: 150 },
    { title: "Golden Gai evening", theme: 1, perPerson: 60, kind: "food", minutes: 150, estimate: true },
    { title: "Mount Fuji and Lake Kawaguchi day trip", theme: 2, perPerson: 140, minutes: 600 },
    { title: "Nikko shrines day trip", theme: 2, perPerson: 110, minutes: 600 },
    { title: "Kamakura Great Buddha day trip", theme: 2, perPerson: 45, minutes: 480 },
    { title: "Hakone hot springs day trip", theme: 2, perPerson: 130, minutes: 600, estimate: true },
  ],
};

const COLORADO_SPRINGS: Profile = {
  match: /colorado springs/i,
  flightPerPerson: 250,
  hotelPerRoomNight: 160,
  dailyPerPerson: 45,
  themes: ["Classic sights", "Outdoors", "Town and food"],
  activities: [
    { title: "Garden of the Gods visitor center and trails", theme: 0, perPerson: 0, minutes: 150 },
    { title: "Pikes Peak Cog Railway", theme: 0, perPerson: 65, minutes: 240 },
    { title: "Manitou Incline hike", theme: 1, perPerson: 0, minutes: 180 },
    { title: "Seven Falls", theme: 1, perPerson: 22, minutes: 120 },
    { title: "Old Colorado City walk and lunch", theme: 2, perPerson: 35, kind: "food", minutes: 150, estimate: true },
    { title: "Cheyenne Mountain Zoo", theme: 2, perPerson: 30, minutes: 180 },
  ],
};

const UKRAINE: Profile = {
  match: /ukraine|kyiv|kiev|lviv|odesa|odessa/i,
  flightPerPerson: 520,
  hotelPerRoomNight: 70,
  dailyPerPerson: 40,
  themes: ["Old town and history", "Food and cafés", "Parks and museums"],
  safety:
    "Government travel advisories warn against travel to this destination. Conditions change quickly, and map and opening-hours data may be out of date.",
  activities: [
    { title: "Old town walking tour", theme: 0, perPerson: 15, minutes: 150, estimate: true },
    { title: "Cathedral and bell tower", theme: 0, perPerson: 5, minutes: 90 },
    { title: "History museum", theme: 0, perPerson: 6, minutes: 120 },
    { title: "Coffee and pastry tasting", theme: 1, perPerson: 20, kind: "food", minutes: 120 },
    { title: "Traditional dinner", theme: 1, perPerson: 30, kind: "food", minutes: 120, estimate: true },
    { title: "City park and botanical garden", theme: 2, perPerson: 3, minutes: 120 },
    { title: "Art museum", theme: 2, perPerson: 6, minutes: 120 },
  ],
};

function genericProfile(destination: string): Profile {
  const place = destination.split(",")[0].trim() || "the city";
  return {
    match: /.*/,
    flightPerPerson: 900,
    hotelPerRoomNight: 150,
    dailyPerPerson: 70,
    themes: ["Culture and history", "Food and nightlife", "Outdoors and day trips"],
    activities: [
      { title: `${place} old town walking tour`, theme: 0, perPerson: 20, minutes: 150, estimate: true },
      { title: `${place} history museum`, theme: 0, perPerson: 15, minutes: 120 },
      { title: `${place} cathedral or main landmark`, theme: 0, perPerson: 12, minutes: 90 },
      { title: `${place} street food tour`, theme: 1, perPerson: 70, kind: "food", minutes: 180 },
      { title: `${place} cooking class`, theme: 1, perPerson: 90, kind: "food", minutes: 180 },
      { title: `${place} evening bar walk`, theme: 1, perPerson: 60, kind: "food", minutes: 150, estimate: true },
      { title: `Day trip from ${place}`, theme: 2, perPerson: 110, minutes: 540 },
      { title: `${place} park and viewpoint hike`, theme: 2, perPerson: 0, minutes: 180 },
      { title: `Boat or bike tour of ${place}`, theme: 2, perPerson: 45, minutes: 150 },
    ],
  };
}

export function profileFor(destination: string): Profile {
  return [TOKYO, COLORADO_SPRINGS, UKRAINE].find((p) => p.match.test(destination)) ?? genericProfile(destination);
}

function slug(text: string): string {
  return text.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
}

export type MockResearch = {
  options: Option[];
  flightId?: string;
  hotelId?: string;
  driveId?: string;
  /** Activity ids grouped by theme 0..2. */
  byTheme: [string[], string[], string[]];
  themes: [string, string, string];
  /** Meals and local transport for the whole trip, not tied to an option. */
  otherCosts: number;
  safety?: string;
};

/** Builds the fake options the research agent would have saved for a trip. */
export function mockResearch(tripId: string, trip: TripRequest, fetchedAt: string): MockResearch {
  const profile = profileFor(trip.destination);
  const people = trip.travelers;
  const nights = Math.max(0, trip.duration_days - 1);
  const rooms = Math.ceil(people / 2);
  const currency = trip.budget.currency;
  const money = (amount: number) => ({ amount, currency });
  const url = (what: string) => `https://example.com/mock/${slug(what)}`;
  const options: Option[] = [];
  const research: MockResearch = {
    options,
    byTheme: [[], [], []],
    themes: profile.themes,
    otherCosts: profile.dailyPerPerson * people * trip.duration_days,
    safety: profile.safety,
  };

  if (trip.transport_mode === "fly") {
    research.flightId = `${tripId}-flight`;
    options.push({
      id: research.flightId,
      kind: "flight",
      title: `Round trip ${trip.origin} – ${trip.destination}`,
      description: "1 stop each way, economy, 1 checked bag",
      price: money(profile.flightPerPerson * people),
      price_is_estimate: false,
      source_url: url(`flight ${trip.destination}`),
      fetched_at: fetchedAt,
      details: { stops: 1, cabin: "economy" },
    });
  } else {
    research.driveId = `${tripId}-drive`;
    options.push({
      id: research.driveId,
      kind: "transport",
      title: `Round-trip drive from ${trip.origin}`,
      description: "Gas and parking, rounded up",
      price: money(60),
      price_is_estimate: true,
      source_url: url(`drive ${trip.destination}`),
      fetched_at: fetchedAt,
      duration_minutes: 90,
    });
  }

  if (nights > 0) {
    research.hotelId = `${tripId}-hotel`;
    options.push({
      id: research.hotelId,
      kind: "hotel",
      title: `Central hotel, ${trip.destination}`,
      description: `${nights} night${nights === 1 ? "" : "s"}, ${rooms} room${rooms === 1 ? "" : "s"}, taxes included`,
      price: money(profile.hotelPerRoomNight * rooms * nights),
      price_is_estimate: false,
      source_url: url(`hotel ${trip.destination}`),
      fetched_at: fetchedAt,
    });
  }

  profile.activities.forEach((a, i) => {
    const id = `${tripId}-act-${i}`;
    research.byTheme[a.theme].push(id);
    options.push({
      id,
      kind: a.kind ?? "activity",
      title: a.title,
      price: money(a.perPerson * people),
      price_is_estimate: a.estimate ?? false,
      source_url: url(a.title),
      fetched_at: fetchedAt,
      duration_minutes: a.minutes,
    });
  });

  return research;
}

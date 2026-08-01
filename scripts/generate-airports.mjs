import { mkdir, readFile, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "..");
const dataDirectory = path.join(root, "work", "airport-data");
const airportSource = path.join(dataDirectory, "airports.csv");
const citySource = path.join(dataDirectory, "china-city-info.json");
const output = path.join(root, "app", "airports.ts");

const sources = {
  [airportSource]: "https://ourairports.com/data/airports.csv",
  [citySource]: "https://cdn.jsdelivr.net/gh/zhChuXiao/ChinaGeoJson@master/info.json",
};

const airportNameOverrides = {
  PEK: "首都", PKX: "大兴", SHA: "虹桥", PVG: "浦东", CAN: "白云", SZX: "宝安",
  CTU: "双流", TFU: "天府", CKG: "江北", XIY: "咸阳", HGH: "萧山", WUH: "天河",
  KMG: "长水", NKG: "禄口", XMN: "高崎", TSN: "滨海", TAO: "胶东", DLC: "周水子",
  SHE: "桃仙", HRB: "太平", CGQ: "龙嘉", TNA: "遥墙", CGO: "新郑", CSX: "黄花",
  HFE: "新桥", KHN: "昌北", FOC: "长乐", JJN: "晋江", WUX: "硕放", NGB: "栎社",
  WNZ: "龙湾", NTG: "兴东", YIW: "义乌", ZUH: "金湾", SWA: "潮汕", HAK: "美兰",
  SYX: "凤凰", NNG: "吴圩", KWL: "两江", BHY: "福成", KWE: "龙洞堡", LJG: "三义",
  JHG: "嘎洒", DLU: "凤仪", DIG: "迪庆香格里拉", URC: "天山", KHG: "徕宁", LXA: "贡嘎",
  XNN: "曹家堡", LHW: "中川", INC: "河东", HET: "白塔", SJW: "正定", TYN: "武宿",
  YNT: "蓬莱", WEH: "大水泊", DYG: "荷花", ENH: "许家坪", JZH: "九寨黄龙",
};

const popularNames = [
  "北京", "上海", "广州", "深圳", "成都", "重庆", "杭州", "南京", "武汉", "西安",
  "长沙", "天津", "青岛", "厦门", "昆明", "苏州", "郑州", "三亚", "海口", "哈尔滨",
  "沈阳", "大连", "济南", "福州", "合肥", "南昌", "宁波", "无锡", "桂林", "贵阳",
];

await mkdir(dataDirectory, { recursive: true });
for (const [file, url] of Object.entries(sources)) {
  if (existsSync(file)) continue;
  const response = await fetch(url);
  if (!response.ok) throw new Error(`下载数据失败：${url} (${response.status})`);
  await writeFile(file, Buffer.from(await response.arrayBuffer()));
}

function parseCsv(text) {
  const rows = [];
  let row = [];
  let cell = "";
  let quoted = false;
  for (let index = 0; index < text.length; index += 1) {
    const character = text[index];
    if (quoted) {
      if (character === '"' && text[index + 1] === '"') {
        cell += '"';
        index += 1;
      } else if (character === '"') {
        quoted = false;
      } else {
        cell += character;
      }
    } else if (character === '"') {
      quoted = true;
    } else if (character === ",") {
      row.push(cell);
      cell = "";
    } else if (character === "\n") {
      row.push(cell.replace(/\r$/, ""));
      rows.push(row);
      row = [];
      cell = "";
    } else {
      cell += character;
    }
  }
  return rows;
}

function cleanPlaceName(name) {
  return name
    .replace(/壮族苗族自治州$|布依族苗族自治州$|哈尼族彝族自治州$|傣族景颇族自治州$/, "")
    .replace(/藏族羌族自治州$|蒙古族藏族自治州$|柯尔克孜自治州$|哈萨克自治州$/, "")
    .replace(/傣族自治州$|彝族自治州$|藏族自治州$|回族自治州$|蒙古族自治州$/, "")
    .replace(/自治州$|地区$|市$|县$/, "");
}

function haversine(lat1, lon1, lat2, lon2) {
  const radians = (degrees) => degrees * Math.PI / 180;
  const latitudeDelta = radians(lat2 - lat1);
  const longitudeDelta = radians(lon2 - lon1);
  const value = Math.sin(latitudeDelta / 2) ** 2
    + Math.cos(radians(lat1)) * Math.cos(radians(lat2)) * Math.sin(longitudeDelta / 2) ** 2;
  return 6371 * 2 * Math.atan2(Math.sqrt(value), Math.sqrt(1 - value));
}

function nearest(list, latitude, longitude, limit = 5) {
  return list
    .map((item) => ({ item, distanceKm: Math.round(haversine(latitude, longitude, item.latitude, item.longitude)) }))
    .sort((left, right) => left.distanceKm - right.distanceKm)
    .slice(0, limit);
}

const csvRows = parseCsv(await readFile(airportSource, "utf8"));
const headers = Object.fromEntries(csvRows[0].map((header, index) => [header, index]));
const airportsRaw = csvRows.slice(1)
  .filter((row) => row[headers.iso_country] === "CN" && row[headers.scheduled_service] === "yes" && row[headers.iata_code])
  .map((row) => ({
    code: row[headers.iata_code],
    englishName: row[headers.name],
    latitude: Number(row[headers.latitude_deg]),
    longitude: Number(row[headers.longitude_deg]),
    municipality: row[headers.municipality],
  }))
  .sort((left, right) => left.code.localeCompare(right.code));

const administrativeData = JSON.parse(await readFile(citySource, "utf8"));
const allPlaces = Object.values(administrativeData);
const mainlandProvinceCodes = new Set(
  allPlaces
    .filter((place) => place.level === "province" && ![710000, 810000, 820000].includes(place.adcode))
    .map((place) => place.adcode),
);
const provinces = Object.fromEntries(
  allPlaces.filter((place) => mainlandProvinceCodes.has(place.adcode)).map((place) => [place.adcode, cleanPlaceName(place.name)]),
);
const mainPlaces = allPlaces.filter((place) =>
  place.center && (place.level === "city" || (place.level === "province" && [110000, 120000, 310000, 500000].includes(place.adcode)))
  && mainlandProvinceCodes.has(place.level === "province" ? place.adcode : place.parent?.adcode),
);

const airports = airportsRaw.map((airport) => {
  const closestCity = nearest(
    mainPlaces.map((place) => ({ ...place, latitude: place.center[1], longitude: place.center[0] })),
    airport.latitude,
    airport.longitude,
    1,
  )[0].item;
  const airportLabel = airportNameOverrides[airport.code]
    || airport.englishName.replace(/\s+(International\s+)?Airport$/i, "");
  return {
    code: airport.code,
    city: cleanPlaceName(closestCity.name),
    airport: airportLabel,
    englishName: airport.englishName,
    latitude: Number(airport.latitude.toFixed(6)),
    longitude: Number(airport.longitude.toFixed(6)),
  };
});

const searchablePlaces = allPlaces.filter((place) => {
  if (!place.center || !["city", "district", "province"].includes(place.level)) return false;
  const provinceCode = place.level === "province" ? place.adcode : place.acroutes?.[1] || place.parent?.adcode;
  if (!mainlandProvinceCodes.has(provinceCode)) return false;
  if (place.level === "province" && ![110000, 120000, 310000, 500000].includes(place.adcode)) return false;
  return !["市辖区", "县"].includes(place.name);
});

const cityOptions = searchablePlaces.map((place) => {
  const provinceCode = place.level === "province" ? place.adcode : place.acroutes?.[1] || place.parent?.adcode;
  const city = cleanPlaceName(place.name);
  const nearby = nearest(airports, place.center[1], place.center[0]).map(({ item, distanceKm }) => ({
    code: item.code,
    distanceKm,
  }));
  return {
    id: String(place.adcode),
    city,
    fullName: place.name,
    province: provinces[provinceCode] || "",
    level: place.level === "district" ? "district" : "city",
    popular: popularNames.includes(city),
    nearby,
  };
}).sort((left, right) => {
  const leftPopular = popularNames.indexOf(left.city);
  const rightPopular = popularNames.indexOf(right.city);
  if (leftPopular !== -1 || rightPopular !== -1) {
    if (leftPopular === -1) return 1;
    if (rightPopular === -1) return -1;
    if (leftPopular !== rightPopular) return leftPopular - rightPopular;
  }
  if (left.level !== right.level) return left.level === "city" ? -1 : 1;
  return Number(left.id) - Number(right.id);
});

const serialize = (value) => JSON.stringify(value);
const generated = `// Generated by scripts/generate-airports.mjs. Do not edit by hand.
// Airport source: OurAirports scheduled-service airports in mainland China with IATA codes.
// City coordinates: zhChuXiao/ChinaGeoJson administrative centers.

export type City = { code: string; city: string; airport: string };
export type Airport = City & { englishName: string; latitude: number; longitude: number };
export type NearbyAirport = { code: string; distanceKm: number };
export type CityOption = {
  id: string;
  city: string;
  fullName: string;
  province: string;
  level: "city" | "district";
  popular: boolean;
  nearby: NearbyAirport[];
};

export const airports: Airport[] = ${serialize(airports)};

export const cityOptions: CityOption[] = ${serialize(cityOptions)};

// Kept as an alias for the flight response types and existing API consumers.
export const cities = airports;
export const cityMap: Record<string, Airport> = Object.fromEntries(
  airports.map((airport) => [airport.code, airport]),
);
`;

if (airports.length < 250) throw new Error(`机场数量异常：仅生成 ${airports.length} 个`);
if (new Set(airports.map((airport) => airport.code)).size !== airports.length) throw new Error("机场三字码重复");
if (!cityOptions.some((option) => option.city === "苏州" && option.nearby.length)) throw new Error("缺少苏州最近机场映射");

await writeFile(output, generated);
console.log(`已生成 ${airports.length} 个机场、${cityOptions.length} 个城市/区县，写入 ${path.relative(root, output)}`);

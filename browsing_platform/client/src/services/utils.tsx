export const cn = (optionalClasses: { [key: string]: boolean }) => {
    return Array.from(Object.entries(optionalClasses)).filter(([i, v]) => {
        return v
    }).map(([i, v]) => i).join(" ")
};

export const toUpperEnglish = (s: string) => {
    // noinspection NonAsciiCharacters
    const qwerty: { [id: string]: string } = {
        "/": "Q", "'": "W", "ק": "E", "ר": "R", "א": "T", "ט": "Y", "ו": "U", "ן": "I", "ם": "O", "פ": "P", "]": "[",
        "[": "]", "ש": "A", "ד": "S", "ג": "D", "כ": "F", "ע": "G", "י": "H", "ח": "J", "ל": "K", "ך": "L", "ף": ";",
        "ז": "Z", "ס": "X", "ב": "C", "ה": "V", "נ": "B", "מ": "N", "צ": "M", "ת": ",", "ץ": ".",
    };
    return s.split("").map(char => {
        return qwerty[char] ? qwerty[char] : char
    }).join("").toUpperCase();
};

export const ISOtoShortDate = (datetime: string) => {
    try {
        return datetime.split("T")[0]
    } catch (e) {
        return JSON.stringify(datetime)
    }
}

export const dateStringToShortDate = (dateString: string) => {
    try {
        const asDate = new Date(dateString)
        return ISOtoShortDate(asDate.toISOString())
    } catch (e) {
        return dateString
    }
}

export const removeUndefinedValues = (obj: any) => {
    if (typeof obj === "object") {
        Object.keys(obj).forEach(key => obj[key] === undefined ? delete obj[key] : {});
    }
    return JSON.parse(JSON.stringify(obj, (key, value) => value === undefined ? null : value));
}


export const cleanKeys = (obj: any, keysToRemove: string[]): void => {
    if (Array.isArray(obj)) {
        obj.forEach(item => cleanKeys(item, keysToRemove));
    } else if (obj !== null && typeof obj === 'object') {
        Object.keys(obj).forEach(key => {
            if (keysToRemove.includes(key)) {
                delete obj[key];
            } else {
                cleanKeys(obj[key], keysToRemove);
            }
        });
    }
}

export const isValidHttpUrl = (str: string) => {
    let url;
    try {
        if(!str.includes(".")){
            return false; // Not a valid URL if it doesn't contain a dot
        }
        url = new URL(str);
    } catch (_) {
        return false;
    }
    return url.protocol === "http:" || url.protocol === "https:";
}
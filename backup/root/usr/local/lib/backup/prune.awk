# Grandfather-father-son selection for one backup set.
# Input is archive basenames, newest first. The stamp is
# YYYY-Www-D-HH-MM-SS and sorts in time order.
# Output lines are "keep <name>" or "drop <name>".

function div(n, d) {
    return int(n / d)
}

function days_from_civil(y, m, d,    era, yoe, doy, doe) {
    if (m <= 2) {
        y = y - 1
    }
    if (y >= 0) {
        era = div(y, 400)
    } else {
        era = div(y - 399, 400)
    }
    yoe = y - era * 400
    if (m > 2) {
        doy = div(153 * (m - 3) + 2, 5) + d - 1
    } else {
        doy = div(153 * (m + 9) + 2, 5) + d - 1
    }
    doe = yoe * 365 + div(yoe, 4) - div(yoe, 100) + doy
    return era * 146097 + doe - 719468
}

function civil_from_days(z,    era, doe, yoe, y, doy, mp, d, m) {
    z += 719468
    if (z >= 0) {
        era = div(z, 146097)
    } else {
        era = div(z - 146096, 146097)
    }
    doe = z - era * 146097
    yoe = div(doe - div(doe, 1460) + div(doe, 36524) - div(doe, 146096), 365)
    y = yoe + era * 400
    doy = doe - (365 * yoe + div(yoe, 4) - div(yoe, 100))
    mp = div(5 * doy + 2, 153)
    d = doy - div(153 * mp + 2, 5) + 1
    if (mp < 10) {
        m = mp + 3
    } else {
        m = mp - 9
    }
    if (m <= 2) {
        y = y + 1
    }
    civil_y = y
    civil_m = m
    civil_d = d
}

function iso_unix(y, w, wd,    jan4, jan4wd, week1) {
    jan4 = days_from_civil(y, 1, 4)
    jan4wd = (jan4 + 3) % 7
    if (jan4wd < 0) {
        jan4wd += 7
    }
    jan4wd += 1
    week1 = jan4 - (jan4wd - 1)
    return week1 + (w - 1) * 7 + (wd - 1)
}

BEGIN {
    split(anchor, parts, "-")
    anchor_day = days_from_civil(parts[1] + 0, parts[2] + 0, parts[3] + 0)
    civil_from_days(anchor_day)
    anchor_month = civil_y * 12 + civil_m
    # Weekday of the anchor: 1970-01-01 is Thursday.
    anchor_wd = (anchor_day + 3) % 7
    if (anchor_wd < 0) {
        anchor_wd += 7
    }
    anchor_wd += 1
    anchor_monday = anchor_day - (anchor_wd - 1)
}

{
    name = $0
    if (!match(name, /-([0-9][0-9][0-9][0-9])-W([0-9][0-9])-([1-7])-[0-9][0-9]-[0-9][0-9]-[0-9][0-9]\.tar\.xz$/)) {
        next
    }
    # match() sets RSTART/RLENGTH on the whole match. Re-parse the stamp.
    stamp = substr(name, RSTART + 1, RLENGTH - 1 - length(".tar.xz"))
    split(stamp, bits, "-")
    year = substr(bits[1], 1, 4) + 0
    week = substr(bits[2], 2, 2) + 0
    wday = bits[3] + 0
    unix = iso_unix(year, week, wday)
    monday = iso_unix(year, week, 1)
    civil_from_days(unix)
    month = civil_y * 12 + civil_m
    count += 1
    names[count] = name
    days[count] = unix
    mondays[count] = monday
    months[count] = month
}

END {
    for (i = 1; i <= count; i++) {
        keep = 0
        if (!(days[i] in seen_day)) {
            seen_day[days[i]] = 1
            delta = anchor_day - days[i]
            if (delta >= 0 && delta < daily) {
                keep = 1
            }
        }
        if (!(mondays[i] in seen_week)) {
            seen_week[mondays[i]] = 1
            delta = div(anchor_monday - mondays[i], 7)
            if (delta >= 0 && delta < weekly) {
                keep = 1
            }
        }
        if (!(months[i] in seen_month)) {
            seen_month[months[i]] = 1
            delta = anchor_month - months[i]
            if (delta >= 0 && delta < monthly) {
                keep = 1
            }
        }
        if (i == 1) {
            keep = 1
        }
        if (keep) {
            print "keep " names[i]
        } else {
            print "drop " names[i]
        }
    }
}

import React from 'react';
import {Stack} from '@mui/material';
import {DatePicker} from '@mui/x-date-pickers/DatePicker';
import {PickerChangeHandlerContext, DateValidationError} from '@mui/x-date-pickers';
import dayjs, {Dayjs} from 'dayjs';

// No archived content predates 2000, so we treat any earlier date as invalid. This is what
// makes keyboard entry usable: while typing a 4-digit year (e.g. "2025"), every intermediate
// value ("0002", "0020", "0202") is < 2000 and is reported by the picker as a minDate
// validation error — so we don't commit a half-typed year as a search. The full year only
// validates once complete, because no prefix of a 4-digit year >= 2000 is itself >= 2000.
const MIN_DATE = dayjs('2000-01-01');
import {MuiConfig, Utils} from '@react-awesome-query-builder/mui';
import {ADVANCED_FILTERS_CONFIG, T_Search_Mode} from '../../services/DataFetcher';
import {SearchShortcutsProps} from './AccountSearchShortcuts';

function isGteRule(rule: any, field: string): boolean {
    return rule?.[">="] != null && Array.isArray(rule[">="]) && rule[">="][0]?.var === field;
}

function isLteRule(rule: any, field: string): boolean {
    return rule?.["<="] != null && Array.isArray(rule["<="]) && rule["<="][0]?.var === field;
}

function extractDateBound(logic: any, field: string, op: ">=" | "<="): string | null {
    if (!logic) return null;
    const checker = op === ">=" ? isGteRule : isLteRule;
    if (checker(logic, field)) return logic[op][1] as string;
    if (Array.isArray(logic.and)) {
        for (const item of logic.and) {
            const val = extractDateBound(item, field, op);
            if (val !== null) return val;
        }
    }
    return null;
}

function removeDateBound(logic: any, field: string, op: ">=" | "<="): any {
    if (!logic) return null;
    const checker = op === ">=" ? isGteRule : isLteRule;
    if (checker(logic, field)) return null;
    if (Array.isArray(logic.and)) {
        const filtered = logic.and.filter((item: any) => !checker(item, field));
        if (filtered.length === 0) return null;
        if (filtered.length === 1) return filtered[0];
        return {"and": filtered};
    }
    return logic;
}

function setDateBound(logic: any, field: string, op: ">=" | "<=", value: string): any {
    // Remove any existing rule for this bound first, then add the new one
    const withoutOld = removeDateBound(logic, field, op);
    const newRule = {[op]: [{"var": field}, value]};
    if (!withoutOld) return newRule;
    if (Array.isArray(withoutOld.and)) return {"and": [...withoutOld.and, newRule]};
    return {"and": [withoutOld, newRule]};
}

interface DateRangeShortcutProps extends SearchShortcutsProps {
    field: string;
    mode: T_Search_Mode;
    fromLabel?: string;
    toLabel?: string;
}

function DateRangeShortcut({tree, onChange, field, mode, fromLabel = "From", toLabel = "To"}: DateRangeShortcutProps) {
    const config = {...MuiConfig, fields: ADVANCED_FILTERS_CONFIG[mode]};
    const logic = Utils.Export.jsonLogicFormat(tree, config).logic;

    const fromStr = extractDateBound(logic, field, ">=");
    const toStr = extractDateBound(logic, field, "<=");

    const fromValue: Dayjs | null = fromStr ? dayjs(fromStr) : null;
    const toValue: Dayjs | null = toStr ? dayjs(toStr) : null;

    const handleFromChange = (val: Dayjs | null, context: PickerChangeHandlerContext<DateValidationError>) => {
        // Ignore in-progress/invalid input (incomplete date, year < 2000, etc.) so we don't
        // commit a search — and remount the page out from under the input — before the user
        // has finished typing. A genuine clear (null value, no error) still removes the bound.
        if (context.validationError) return;
        let newLogic: any;
        if (!val || !val.isValid()) {
            newLogic = removeDateBound(logic, field, ">=") ?? null;
        } else {
            newLogic = setDateBound(logic, field, ">=", val.format("YYYY-MM-DD"));
        }
        onChange(newLogic);
    };

    const handleToChange = (val: Dayjs | null, context: PickerChangeHandlerContext<DateValidationError>) => {
        if (context.validationError) return;
        let newLogic: any;
        if (!val || !val.isValid()) {
            newLogic = removeDateBound(logic, field, "<=") ?? null;
        } else {
            newLogic = setDateBound(logic, field, "<=", val.format("YYYY-MM-DD"));
        }
        onChange(newLogic);
    };

    return (
        <Stack direction="row" spacing={2} alignItems="center">
            <DatePicker
                label={fromLabel}
                value={fromValue}
                onChange={handleFromChange}
                format="DD/MM/YYYY"
                minDate={MIN_DATE}
                slotProps={{textField: {size: "small"}}}
            />
            <DatePicker
                label={toLabel}
                value={toValue}
                onChange={handleToChange}
                format="DD/MM/YYYY"
                minDate={MIN_DATE}
                slotProps={{textField: {size: "small"}}}
            />
        </Stack>
    );
}

export function createDateRangeShortcut(
    field: string,
    mode: T_Search_Mode,
    fromLabel?: string,
    toLabel?: string,
): React.FC<SearchShortcutsProps> {
    return function DateRangeShortcutInstance({tree, onChange}: SearchShortcutsProps) {
        return <DateRangeShortcut tree={tree} onChange={onChange} field={field} mode={mode} fromLabel={fromLabel} toLabel={toLabel}/>;
    };
}

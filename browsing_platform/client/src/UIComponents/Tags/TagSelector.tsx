import React, {useRef, useState} from 'react';
import Chip from '@mui/material/Chip';
import Autocomplete from '@mui/material/Autocomplete';
import TextField from '@mui/material/TextField';
import Stack from '@mui/material/Stack';
import {lookupTags} from "../../services/DataFetcher";
import {ITagWithType} from "../../types/tags";
import {E_ENTITY_TYPES} from "../../types/entities";
import {Button, Dialog, DialogActions, DialogContent, DialogTitle, Tooltip, Typography} from "@mui/material";

const filterOptions = (x: ITagWithType[]) => x;
const isOptionEqualToValue = (option: ITagWithType, value: ITagWithType) => option.id === value.id;
const getOptionLabel = (option: ITagWithType) => option.name;
const groupBy = (option: ITagWithType) => option.tag_type_name ?? '(No type)';

interface IProps {
    selectedTags: ITagWithType[]
    readOnly?: boolean
    onChange: (tags: ITagWithType[]) => void
    onChipClick?: (tag: ITagWithType) => void
    label?: string
    entity?: E_ENTITY_TYPES
    rapidPrefixSelection?: boolean
    disableDeletionCheck?: boolean
    single?: boolean
}

export default function TagSelector({selectedTags, readOnly, onChange, onChipClick, label = 'Tags', entity, rapidPrefixSelection = false, disableDeletionCheck = false, single = false}: IProps) {
    const [inputValue, setInputValue] = useState('');
    const [fetchingOptions, setFetchingOptions] = useState(false);
    const [options, setOptions] = useState<ITagWithType[]>([]);
    const [pendingDelete, setPendingDelete] = useState<{tag: ITagWithType; onDelete: (e: any) => void} | null>(null);
    const selectedSinceLastInput = useRef(false);

    const fetchMatchingOptions = async (value: string) => {
        setFetchingOptions(true);
        const matchingOptions = await lookupTags(value, entity);
        setOptions([...matchingOptions].sort(
            (a, b) => (a.tag_type_name ?? '').localeCompare(b.tag_type_name ?? '')
                || a.name.localeCompare(b.name)
        ));
        setFetchingOptions(false);
    };

    const noOptionsText = fetchingOptions ? 'Loading…' : (inputValue ? 'No tags found' : 'Start typing to search tags');

    if (single) {
        return (
            <Autocomplete
                value={selectedTags[0] ?? null}
                onChange={(_, newValue) => onChange(newValue ? [newValue] : [])}
                disabled={readOnly === true}
                filterOptions={filterOptions}
                inputValue={inputValue}
                onInputChange={async (_, newInputValue, reason) => {
                    // Sync the controlled input for every reason (incl. 'reset' on
                    // select and 'clear'); otherwise it stays stuck on the typed
                    // prefix instead of the picked tag's name. Fetch only on typing.
                    setInputValue(newInputValue);
                    if (reason === 'input') await fetchMatchingOptions(newInputValue);
                }}
                onClose={() => setOptions([])}
                noOptionsText={noOptionsText}
                isOptionEqualToValue={isOptionEqualToValue}
                getOptionLabel={getOptionLabel}
                groupBy={groupBy}
                options={options}
                loading={fetchingOptions}
                renderInput={(params) => (
                    <TextField {...params} variant="filled" label={label}/>
                )}
            />
        );
    }

    return <><Autocomplete
        value={selectedTags}
        onChange={(_, newValue) => {
            onChange(newValue);
        }}
        disabled={readOnly === true}
        disableCloseOnSelect={rapidPrefixSelection}
        filterOptions={filterOptions}
        inputValue={inputValue}
        onInputChange={async (_, newInputValue, reason) => {
            if (rapidPrefixSelection && reason !== 'input') {
                if (reason === 'selectOption') selectedSinceLastInput.current = true;
                return;
            }
            selectedSinceLastInput.current = false;
            setInputValue(newInputValue);
            await fetchMatchingOptions(newInputValue);
        }}
        onClose={() => {
            if (rapidPrefixSelection && selectedSinceLastInput.current) {
                setInputValue('');
                setOptions([]);
                selectedSinceLastInput.current = false;
            }
        }}
        multiple
        noOptionsText={noOptionsText}
        isOptionEqualToValue={isOptionEqualToValue}
        getOptionLabel={getOptionLabel}
        groupBy={groupBy}
        options={options}
        loading={fetchingOptions}
        renderTags={(value: readonly ITagWithType[], getItemProps) =>
            value.map((option: ITagWithType, index: number) => {
                const {key, onDelete, ...itemProps} = getItemProps({index});
                return (
                    <Tooltip
                        key={key}
                        arrow
                        disableInteractive
                        title={
                            <Stack>
                                <Typography variant={"caption"}>{option.tag_type_name}</Typography>
                                {option.description && <Typography variant={"body1"}>{option.description}</Typography>}
                                {option.assignment_notes && <Typography variant={"body2"} sx={{fontStyle: 'italic'}}>{option.assignment_notes}</Typography>}
                            </Stack>
                        }
                    >
                        <Chip
                            variant={option.assignment_notes ? "filled" : "outlined"}
                            label={option.name}
                            {...itemProps}
                            onDelete={() => {
                                if(disableDeletionCheck){
                                    onDelete(undefined)
                                }
                                else {
                                    setPendingDelete({tag: option, onDelete})
                                }
                            }}
                            onClick={onChipClick ? () => onChipClick(option) : undefined}
                        />
                    </Tooltip>
                );
            })
        }
        renderInput={(params) => (
            <TextField {...params} variant="filled" label={label}/>
        )}
    />
    <Dialog open={pendingDelete !== null} onClose={() => setPendingDelete(null)} maxWidth="xs" fullWidth>
        <DialogTitle>Remove tag?</DialogTitle>
        <DialogContent>
            <Typography>Remove "<strong>{pendingDelete?.tag.name}</strong>"?</Typography>
        </DialogContent>
        <DialogActions>
            <Button onClick={() => setPendingDelete(null)}>Cancel</Button>
            <Button color="error" variant="contained" onClick={() => {
                pendingDelete?.onDelete(undefined);
                setPendingDelete(null);
            }}>Remove</Button>
        </DialogActions>
    </Dialog>
</>;
}

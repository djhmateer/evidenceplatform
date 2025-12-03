import React from 'react';
import {IAccount, IMedia, IMediaPart, IPost} from "../../types/entities";
import {Button, CircularProgress, Grow, Stack, Typography} from "@mui/material";
import {ITagWithType} from "../../types/tags";
import TextField from "@mui/material/TextField";
import TagSelector from "../Tags/TagSelector";
import SaveIcon from "@mui/icons-material/Save";
import {saveAccountAnnotations, saveMediaAnnotations, savePostAnnotations} from "../../services/DataSaver";
import {toast} from "material-react-toastify";

interface IProps {
    entity: IMedia | IPost | IAccount | IMediaPart
    entityType: "media" | "post" | "account" | "media_part"
    readonly: boolean,
    onSave?: () => void
}

interface IAnnotations {
    notes: string
    tags: ITagWithType[]
}

interface IState {
    annotations: IAnnotations
    unsavedChanges?: boolean
    awaitingSave: boolean;
}


export default class EntityAnnotator extends React.Component <IProps, IState> {
    constructor(props: IProps) {
        super(props);
        console.log(props.entity.tags)
        this.state = {
            annotations: {
                notes: props.entity.notes || "",
                tags: props.entity.tags || [],
            },
            unsavedChanges: false,
            awaitingSave: false
        };
    }

    private async saveAnnotations() {
        this.setState((curr) => ({...curr, savingAnnotations: true}), async () => {
            const {annotations} = this.state;
            const {entityType, entity} = this.props;
            const updatedEntity = {...entity, notes: annotations.notes, tags: annotations.tags};
            switch (entityType) {
                case "media":
                    await saveMediaAnnotations(updatedEntity as IMedia);
                    break;
                case "post":
                    await savePostAnnotations(updatedEntity as IPost);
                    break;
                case "account":
                    await saveAccountAnnotations(updatedEntity as IAccount);
                    break;
                case "media_part":
                    break;
            }
            if (this.props.onSave) {
                this.props.onSave();
            }
            toast.success("Annotations saved successfully.");
            this.setState((curr) => ({...curr, savingAnnotations: false, unsavedChanges: false}));
        });
    }

    render() {
        const {notes, tags} = this.state.annotations;
        if (this.props.readonly) {
            return <Stack gap={1}>
                <Typography variant={"h6"}>Notes</Typography>
                <Typography variant={"body2"}>{notes || "No notes available."}</Typography>
                <Typography variant={"h6"}>Tags</Typography>
                {
                    tags.length === 0
                        ? <Typography variant={"body2"}>No tags available.</Typography>
                        : <Stack direction={"row"} gap={1} flexWrap={"wrap"}>
                            {
                                tags.map((tag, index) => <Typography variant={"body2"} key={index} sx={{
                                    padding: '0.2em 0.5em',
                                    backgroundColor: '#e0e0e0',
                                    borderRadius: '4px'
                                }}>{tag.name}</Typography>)
                            }
                        </Stack>
                }
            </Stack>
        } else {
            return <Stack gap={1}>
                <TextField
                    label={"Notes"}
                    multiline
                    value={notes || ""}
                    onChange={(e) => {
                        const annotations = this.state.annotations;
                        annotations.notes = e.target.value;
                        this.setState((curr) => ({...curr, annotations, unsavedChanges: true}))
                    }}
                />
                <TagSelector
                    selectedTags={this.state.annotations.tags}
                    onChange={(tags) => {
                        const annotations = this.state.annotations;
                        annotations.tags = tags;
                        this.setState((curr) => ({...curr, annotations, unsavedChanges: true}))
                    }}
                />
                <Grow in={this.state.unsavedChanges} unmountOnExit>
                    <Button
                        variant="contained"
                        startIcon={this.state.awaitingSave ? <CircularProgress size={20} color={"inherit"}/> :
                            <SaveIcon/>}
                        onClick={async () => {
                            await this.saveAnnotations();
                        }}
                        color={"success"}
                    >
                        Save Annotations
                    </Button>
                </Grow>
            </Stack>
        }
    }
}

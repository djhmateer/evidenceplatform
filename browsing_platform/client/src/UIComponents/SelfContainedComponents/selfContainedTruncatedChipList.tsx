import React, {Component} from 'react';
import {Chip, ChipTypeMap, Stack, StackTypeMap, Tooltip} from '@mui/material';
import './selfContainedModal.scss';
import {DefaultComponentProps} from "@mui/material/OverridableComponent";

interface IProps {
    chipContents: string[],
    chipsVisibleWhenCollapsed: number,
    expandedByDefault?: boolean,
    stackProps: DefaultComponentProps<StackTypeMap>
    chipProps?: DefaultComponentProps<ChipTypeMap>
}


interface IState {
    expanded: boolean;
}

export default class SelfContainedTruncatedChipList extends Component<IProps, IState> {
    constructor(props: IProps) {
        super(props);
        this.state = {
            expanded: !!props.expandedByDefault
        };
    }

    render() {
        const expanded = this.state.expanded;
        const plusN = this.props.chipContents.length - this.props.chipsVisibleWhenCollapsed;
        const plusLabel = this.props.chipContents.length > this.props.chipsVisibleWhenCollapsed ? `+${plusN}` : null;
        return (
            <Stack
                gap={1}
                direction={"row"}
                width={"90%"}
                alignItems={"start"}
                {...this.props.stackProps || {}}
            >
                {
                    this.props.chipContents
                        .filter((_, i) => (expanded || i < this.props.chipsVisibleWhenCollapsed))
                        .map((s, i) => {
                            return <Chip
                                key={i}
                                label={s}
                                size={"small"}
                                variant={"outlined"}
                                onClick={expanded ? () => {
                                    this.setState((curr) => ({...curr, expanded: false}))
                                } : undefined}
                                sx={{
                                    maxWidth: `calc(100% - ${(plusLabel?.length || 0) * 1.25}em)`
                                }}
                                {...this.props.chipProps || {}}
                            />
                        })
                }
                {
                    !expanded && plusLabel ?
                        <Tooltip
                            title={
                                <Stack
                                    gap={1}
                                    direction={"column"}
                                    width={"100%"}
                                    alignItems={"start"}
                                >
                                    {
                                        this.props.chipContents
                                            .filter((_, i) => i >= this.props.chipsVisibleWhenCollapsed)
                                            .map((s, i) => {
                                                return <Chip
                                                    key={i}
                                                    label={s}
                                                    size={"small"}
                                                    variant={"outlined"}
                                                    sx={{backgroundColor: "white"}}
                                                />
                                            })
                                    }
                                </Stack>
                            }
                            arrow
                        >
                            <Chip
                                label={plusLabel}
                                size={"small"}
                                variant={"outlined"}
                                {...this.props.chipProps || {}}
                                onClick={() => {
                                    this.setState((curr) => ({...curr, expanded: true}))
                                }}
                            />
                        </Tooltip> :
                        null
                }
            </Stack>
        );
    }
}


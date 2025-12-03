import React, {Component, ReactElement} from 'react';
import {Popover, PopoverProps} from '@mui/material';

interface IProps {
    trigger: (popupVisibilitySetter: (e: React.MouseEvent<HTMLElement>, visibility: boolean) => any) => ReactElement;
    content: (popupVisibilitySetter: (visibility: boolean) => any) => ReactElement;
    popoverProps?: Partial<PopoverProps>
}


interface IState {
    visible: boolean;
    anchorEl: HTMLElement | null;
}

export default class SelfContainedPopover extends Component<IProps, IState> {
    constructor(props: IProps) {
        super(props);
        this.state = {
            visible: false,
            anchorEl: null
        };
    }

    render() {
        return (
            <React.Fragment>
                {this.props.trigger((e, visible) => {
                    this.setState({visible, anchorEl: e.currentTarget})
                })}
                <Popover
                    open={this.state.visible}
                    onClose={() => {
                        this.setState({visible: false})
                    }}
                    sx={
                        {
                            '& .MuiPaper-root': {
                                padding: '1em'
                            }
                        }
                    }
                    anchorEl={this.state.anchorEl}
                    {...this.props.popoverProps}
                >
                    {
                        this.props.content(
                            (visibility: boolean) => {
                                this.setState({visible: visibility});
                            }
                        )
                    }
                </Popover>
            </React.Fragment>
        );
    }
}


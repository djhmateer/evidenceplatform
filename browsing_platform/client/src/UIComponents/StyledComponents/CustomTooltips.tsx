import {styled, Tooltip, tooltipClasses, TooltipProps} from "@mui/material";
import React from "react";

export const TransparentTooltip = styled(({className, children, ...props}: TooltipProps) => (
    <Tooltip {...props} classes={{popper: className}} children={children}/>
))(({}) => ({
    [`& .${tooltipClasses.tooltip}`]: {
        backgroundColor: "transparent",
        boxShadow: "none",
    },
}));

export const LightTooltip = styled(({ className, ...props }: TooltipProps) => (
  <Tooltip {...props} classes={{ popper: className }} />
))(({ theme }) => ({
  [`& .${tooltipClasses.tooltip}`]: {
    backgroundColor: theme.palette.common.white,
    color: 'rgba(0, 0, 0, 0.87)',
    boxShadow: theme.shadows[1],
    fontSize: 11,
  },
}));

export const NoMaxWidthTooltip = styled(({ className, ...props }: TooltipProps) => (
  <Tooltip {...props} classes={{ popper: className }} />
))({
  [`& .${tooltipClasses.tooltip}`]: {
    maxWidth: 'none',
  },
});
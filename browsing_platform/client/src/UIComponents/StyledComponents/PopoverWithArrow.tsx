import {Popover, type PopoverProps} from '@mui/material';

/**
 * The `Popover` that:
 * - is positioned at the bottom-right of the `anchorEl`, and
 * - has an arrow pointing to the `anchorEl`.
 */
export const PopoverWithArrow = (popoverProps: Omit<PopoverProps, 'anchorOrigin' | 'transformOrigin'>) => (
  <Popover
    anchorOrigin={{ horizontal: 'left', vertical: 'bottom' }}
    transformOrigin={{ horizontal: 10, vertical: -5 }}
    slotProps={{
      paper: {
        sx: {
          overflow: 'visible',
          '&:before': {
            content: '""',
            display: 'block',
            position: 'absolute',
            top: 0,
            left: 11,
            width: 10,
            height: 10,
            backgroundColor: 'inherit',
            transform: 'translateY(-50%) rotate(45deg)',
            boxShadow: '-3px -3px 5px -2px rgba(0,0,0,0.1)',
          },
        },
      },
    }}
    {...popoverProps}
  />
);
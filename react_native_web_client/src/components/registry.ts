/**
 * Component registry: catalog component name  ->  React Native implementation.
 *
 * This is the ONLY place the renderer learns about concrete widgets. Adding a custom component
 * = (1) declare its schema in a2ui/catalog.ts, (2) implement it, (3) add one line here.
 */
import type {ComponentRegistry} from '../a2ui/A2uiRenderer';
import * as B from './basic';
import * as C from './custom';

export const registry: ComponentRegistry = {
  // --- Basic Catalog (18) ---
  Card: B.CardRN,
  Column: B.ColumnRN,
  Row: B.RowRN,
  List: B.ListRN,
  Tabs: B.TabsRN,
  Modal: B.ModalRN,
  Divider: B.DividerRN,
  Text: B.TextRN,
  Image: B.ImageRN,
  Icon: B.IconRN,
  Video: B.VideoRN,
  AudioPlayer: B.AudioPlayerRN,
  Button: B.ButtonRN,
  TextField: B.TextFieldRN,
  CheckBox: B.CheckBoxRN,
  ChoicePicker: B.ChoicePickerRN,
  Slider: B.SliderRN,
  DateTimeInput: B.DateTimeInputRN,
  // --- Custom catalog extensions ---
  StatTile: C.StatTileRN,
  ProfileHeader: C.ProfileHeaderRN,
  ChipStrip: C.ChipStripRN,
  // --- fallback ---
  __unknown__: B.UnknownRN,
};

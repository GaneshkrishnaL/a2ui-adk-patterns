import {AppRegistry} from 'react-native';
import App from './App';

// Standard React Native entry point; react-native-web maps it onto the DOM.
AppRegistry.registerComponent('A2uiDemo', () => App);
AppRegistry.runApplication('A2uiDemo', {rootTag: document.getElementById('root')});

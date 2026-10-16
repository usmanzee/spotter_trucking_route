import { LoaderCircle, MapPin } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";

import { searchLocations } from "../api";
import type { LocationSuggestion } from "../types";

interface LocationAutocompleteProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
}

export function LocationAutocomplete({
  label,
  value,
  onChange,
}: LocationAutocompleteProps) {
  const inputId = useId();
  const listId = useId();
  const blurTimer = useRef<number | null>(null);
  const [suggestions, setSuggestions] = useState<LocationSuggestion[]>([]);
  const [isDirty, setIsDirty] = useState(false);
  const [isOpen, setIsOpen] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [hasSearched, setHasSearched] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);

  useEffect(() => {
    if (!isDirty || value.trim().length < 2) {
      setSuggestions([]);
      setHasSearched(false);
      setIsLoading(false);
      return;
    }

    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      setIsLoading(true);
      try {
        const matches = await searchLocations(value.trim(), controller.signal);
        setSuggestions(matches);
        setActiveIndex(-1);
        setHasSearched(true);
        setIsOpen(true);
      } catch (error) {
        if (!(error instanceof DOMException && error.name === "AbortError")) {
          setSuggestions([]);
          setHasSearched(true);
        }
      } finally {
        if (!controller.signal.aborted) setIsLoading(false);
      }
    }, 300);

    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [isDirty, value]);

  useEffect(
    () => () => {
      if (blurTimer.current !== null) window.clearTimeout(blurTimer.current);
    },
    [],
  );

  function choose(suggestion: LocationSuggestion) {
    onChange(suggestion.label);
    setSuggestions([]);
    setIsDirty(false);
    setIsOpen(false);
    setHasSearched(false);
    setActiveIndex(-1);
  }

  function handleKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    if (!isOpen || suggestions.length === 0) {
      if (event.key === "ArrowDown" && suggestions.length > 0) setIsOpen(true);
      return;
    }
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActiveIndex((index) => Math.min(index + 1, suggestions.length - 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActiveIndex((index) => Math.max(index - 1, 0));
    } else if (event.key === "Enter" && activeIndex >= 0) {
      event.preventDefault();
      choose(suggestions[activeIndex]);
    } else if (event.key === "Escape") {
      setIsOpen(false);
    }
  }

  return (
    <div className="field autocomplete-field">
      <label className="field-label" htmlFor={inputId}>{label}</label>
      <span className="input-shell">
        <MapPin aria-hidden="true" size={18} />
        <input
          id={inputId}
          role="combobox"
          aria-autocomplete="list"
          aria-expanded={isOpen}
          aria-controls={listId}
          aria-activedescendant={
            activeIndex >= 0 ? `${listId}-option-${activeIndex}` : undefined
          }
          value={value}
          onChange={(event) => {
            onChange(event.target.value);
            setIsDirty(true);
            setIsOpen(true);
          }}
          onFocus={() => {
            if (suggestions.length > 0) setIsOpen(true);
          }}
          onBlur={() => {
            blurTimer.current = window.setTimeout(() => setIsOpen(false), 150);
          }}
          onKeyDown={handleKeyDown}
          placeholder="City, state or address"
          required
          maxLength={200}
          autoComplete="off"
        />
        {isLoading && <LoaderCircle className="autocomplete-loader" size={16} />}
      </span>

      {isOpen && (suggestions.length > 0 || hasSearched) && (
        <div className="autocomplete-menu" id={listId} role="listbox">
          {suggestions.length > 0 ? (
            suggestions.map((suggestion, index) => (
              <button
                id={`${listId}-option-${index}`}
                role="option"
                aria-selected={activeIndex === index}
                className={activeIndex === index ? "active" : ""}
                key={suggestion.provider_id}
                type="button"
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => choose(suggestion)}
              >
                <MapPin size={15} />
                <span>{suggestion.label}</span>
                <small>{suggestion.result_type.replaceAll("_", " ")}</small>
              </button>
            ))
          ) : (
            <span className="autocomplete-empty">No matching locations found</span>
          )}
        </div>
      )}
    </div>
  );
}
